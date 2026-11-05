"""The planning agent: a language model plans tomorrow's visits, one step at a time.

The model decides everything. At each step it writes its thinking and picks one action, a tool;
code runs the tool and gives the model the result, and the model picks the next action. This
goes on until the model submits a plan, or runs out of steps. Code never decides what to do
next: it only runs the tools, which give facts and check plans but never choose or order
patients.

Each step is JSON that must follow a schema (Ollama's structured outputs): the action is one of
the tools' names, so the model can't call a tool that doesn't exist or write an answer that
can't be read.

Run it (Ollama must be running):
    python -m homecare.agent examples/18th_avenue.csv --home "6302 18th Ave, Brooklyn"
"""

import argparse
import csv
import dataclasses
import io
import json

from homecare import addresses, llm

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

Answer every step in JSON. Fill in only the fields your action uses; leave the others empty."""


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
    def __init__(self, request: Request, ask=llm.ask, log=print, find=addresses.find):
        self.request, self.ask, self.log, self.find = request, ask, log, find
        self.patient_list, self.ids = numbered(request.csv_text)
        self.found: dict[str, addresses.Place] = {}  # each place found so far: a patient's id, or "home"
        # Each tool: what the model is told it does, the fields it fills in, and the code that runs it.
        self.tools = {
            "find_address": (
                "find_address: find where addresses are on the map. Fill in places: for each, place (a "
                "patient's id, or home) and address (as the list or the task writes it).",
                {"places": {"type": "array", "maxItems": len(self.ids) + 1, "items": {
                    "type": "object",
                    "properties": {"place": {"type": "string", "enum": [*self.ids, "home"]},
                                   "address": {"type": "string"}},
                    "required": ["place", "address"]}}},
                self.find_address,
            ),
            "submit_plan": (
                "submit_plan: hand in your plan and finish. Fill in order: the patients' ids, in visiting order.",
                {"order": {"type": "array", "items": {"type": "string", "enum": self.ids},
                           "maxItems": len(self.ids)}},
                self.submit_plan,
            ),
        }

    def schema(self) -> dict:
        """What every step must look like: thinking, an action, and every tool's fields."""
        fields = {name: spec for _, tool_fields, _ in self.tools.values() for name, spec in tool_fields.items()}
        return {
            "type": "object",
            "properties": {"thinking": {"type": "string"}, "action": {"type": "string", "enum": list(self.tools)},
                           **fields},
            "required": ["thinking", "action", *fields],
        }

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
        return "\n".join(lines) or "No addresses given.", False

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
            arguments = {name: answer[name] for name in self.tools[action][1]}
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
