"""The planning agent: a language model plans tomorrow's visits, one step at a time.

The model decides everything. At each step it writes its thinking and picks one action, a tool;
code runs the tool and gives the model the result, and the model picks the next action. This
goes on until the model submits a plan, or runs out of steps. Code never decides what to do
next: it only runs the tools, which give facts and check plans but never choose or order
patients.

Each step is JSON that must follow a schema (Ollama's structured outputs). The schema has one
shape per tool (anyOf): thinking, the tool's name as the action, then that tool's own fields
only. So the model can't call a tool that doesn't exist, fill in another tool's fields, or
write an answer that can't be read. With every tool's fields in one shape, the model put
travel_times' places into find_address's field and left its own empty.

Run it (Ollama must be running):
    python -m homecare.agent examples/18th_avenue.csv --home "6302 18th Ave, Brooklyn"
"""

import argparse
import csv
import dataclasses
import io
import json

from homecare import addresses, llm, travel

MAX_STEPS = 20  # steps the model may take before it is stopped
MAX_STEP_TOKENS = 600  # the longest one step's answer may be

SYSTEM_PROMPT = """\
You are a planning agent for a home-care nurse. You plan tomorrow's visits: which patients to
see, and in what order.

The goal: visit as many patients as possible, up to the limit. Among plans with the same number
of visits, choose the one with the least travel. Respect each patient's time window, as the
patient list gives it.

You work step by step. At each step, write your thinking, then choose one action:
{actions}

Answer every step in JSON."""


@dataclasses.dataclass
class Request:
    csv_text: str  # the patient list, as the nurse wrote it
    home: str  # the nurse's home address, where the day starts and ends
    day_start: str = "08:00"
    day_end: str = "17:00"
    max_visits: int = 5


@dataclasses.dataclass
class Step:
    thinking: str
    action: str
    arguments: dict
    result: str


@dataclasses.dataclass
class Result:
    order: list[str]  # patient ids, in visiting order; empty if no plan was submitted
    steps: list[Step]
    ended: str  # why the run ended: "submitted", or "step limit"


def numbered(csv_text: str) -> tuple[str, list[str]]:
    """The patient list with an id column in front (P1, P2, ...), and the ids.

    The ids let the model name each patient exactly, whatever the list's own columns are."""
    table = [row for row in csv.reader(io.StringIO(csv_text.strip())) if any(cell.strip() for cell in row)]
    if len(table) < 2:
        raise ValueError("the patient list needs a header row and at least one patient")
    ids = [f"P{number}" for number in range(1, len(table))]
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["id", *table[0]])
    writer.writerows([patient_id, *row] for patient_id, row in zip(ids, table[1:]))
    return out.getvalue(), ids


class Agent:
    def __init__(self, request: Request, ask=llm.ask, log=print, find=addresses.find,
                 minutes=travel.walking_minutes):
        self.request, self.ask, self.log, self.find, self.minutes = request, ask, log, find, minutes
        self.patient_list, self.ids = numbered(request.csv_text)
        self.found: dict[str, addresses.Place] = {}  # each place found so far: a patient's id, or "home"
        # Each tool: what the model is told it does, the fields it fills in, and the code that runs it.
        # minItems keeps a list from being left empty: the model often wrote [] when unsure.
        self.tools = {
            "find_address": (
                "find_address: find where addresses are on the map. Fill in places: for each, place (a "
                "patient's id, or home) and address (as the list or the task writes it).",
                {"places": {"type": "array", "minItems": 1, "maxItems": len(self.ids) + 1, "items": {
                    "type": "object",
                    "properties": {"place": {"type": "string", "enum": [*self.ids, "home"]},
                                   "address": {"type": "string"}},
                    "required": ["place", "address"]}}},
                self.find_address,
            ),
            "travel_times": (
                "travel_times: walking minutes between places whose addresses you found. Fill in between: "
                "the places (patients' ids, or home).",
                {"between": {"type": "array", "items": {"type": "string", "enum": [*self.ids, "home"]},
                             "minItems": 2, "maxItems": len(self.ids) + 1}},
                self.travel_times,
            ),
            "submit_plan": (
                "submit_plan: hand in your plan and finish. Fill in order: the patients' ids, in visiting order.",
                {"order": {"type": "array", "items": {"type": "string", "enum": self.ids},
                           "minItems": 1, "maxItems": len(self.ids)}},
                self.submit_plan,
            ),
        }

    def schema(self) -> dict:
        """What every step must look like: one shape per tool, with thinking, the tool's name, and its fields.

        The model writes the fields in this order, so it thinks first, then picks the tool; once
        the tool's name is written, only that tool's fields can follow."""
        return {"anyOf": [
            {"type": "object",
             "properties": {"thinking": {"type": "string"}, "action": {"type": "string", "enum": [name]},
                            **fields},
             "required": ["thinking", "action", *fields]}
            for name, (_, fields, _) in self.tools.items()
        ]}

    def first_messages(self) -> list[dict]:
        actions = "\n".join(f"- {description}" for description, _, _ in self.tools.values())
        r = self.request
        task = (f"Tomorrow the nurse leaves home at {r.day_start} at the earliest and must be back by "
                f"{r.day_end}. At most {r.max_visits} visits. Home: {r.home}.\n\nPatient list:\n{self.patient_list}")
        return [{"role": "system", "content": SYSTEM_PROMPT.format(actions=actions)},
                {"role": "user", "content": task}]

    # The tools. Each returns what the model is told, and whether the run is over.
    def find_address(self, answer: dict) -> tuple[str, bool]:
        lines = []
        for item in answer["places"]:
            try:
                self.found[item["place"]] = place = self.find(item["address"])
                lines.append(f"{item['place']}: found {place.display}")
            except addresses.AddressError as problem:
                lines.append(f"{item['place']}: {problem}")
        return "\n".join(lines), False

    def travel_times(self, answer: dict) -> tuple[str, bool]:
        asked = list(dict.fromkeys(answer["between"]))  # each place once, in the order asked
        known = [place for place in asked if place in self.found]
        if len(known) < 2:
            lines = ["Travel times need at least two places whose addresses were found."]
        else:
            minutes = self.minutes([self.found[place] for place in known])
            lines = ["Walking minutes:"]
            for i, start in enumerate(known):
                legs = [f"{end} {'no route' if minutes[i][j] is None else minutes[i][j]}"
                        for j, end in enumerate(known) if j != i]
                lines.append(f"from {start}: {', '.join(legs)}")
        lines += [f"{place}: address not found yet; use find_address first" for place in asked if place not in known]
        return "\n".join(lines), False

    def submit_plan(self, answer: dict) -> tuple[str, bool]:
        self.order = answer["order"]
        return "Plan received.", True

    def run(self) -> Result:
        messages, steps, schema = self.first_messages(), [], self.schema()
        self.order, self.found = [], {}
        for number in range(1, MAX_STEPS + 1):
            try:
                answer = self.ask(messages, schema, MAX_STEP_TOKENS)
            except llm.CutOff:
                self.log(f"[{number}] the answer was cut off")
                messages.append({"role": "user", "content": "Your answer was too long and was cut off. Answer again, shorter."})
                continue
            action = answer["action"]
            # Everything the model wrote besides its thinking and action, so the trace hides nothing.
            arguments = {name: value for name, value in answer.items() if name not in ("thinking", "action")}
            result, done = self.tools[action][2](answer)
            steps.append(Step(answer["thinking"], action, arguments, result))
            shown_result = result.replace("\n", "\n       ")  # a result of several lines stays indented
            self.log(f"[{number}] {answer['thinking']}\n    -> {action} {json.dumps(arguments)}\n    <- {shown_result}")
            messages += [{"role": "assistant", "content": json.dumps(answer)},
                         {"role": "user", "content": f"Result of {action}: {result}"}]
            if done:
                return Result(self.order, steps, "submitted")
        return Result([], steps, "step limit")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv", help="the patient list")
    parser.add_argument("--home", required=True, help="the nurse's home address")
    args = parser.parse_args()
    with open(args.csv, encoding="utf-8") as file:
        request = Request(file.read(), args.home)
    result = Agent(request).run()
    print(f"\n{result.ended} after {len(result.steps)} steps: {' -> '.join(result.order) or 'no plan'}")


if __name__ == "__main__":
    main()
