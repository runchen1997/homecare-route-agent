"""The planning agent: a language model plans tomorrow's visits, one step at a time.

The model decides everything. At each step it writes its thinking and picks one action, a tool;
code runs the tool and gives the model the result, and the model picks the next action. This
goes on until the model submits a plan, or runs out of steps. Code never decides what to do
next: it only runs the tools.

The design is a hybrid. Working out the best order is a search over thousands of plans, which a
small model does badly (it handed in plans with 18-33% more walking than the best), so a tool
does it: best_plans tries every plan and gives the best few, each best by a different measure.
The model reads the list (the windows the plans are worked out with are its reading), chooses
among the plans, and hands one in.

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

from homecare import addresses, checking, llm, solving, travel

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
    rules: checking.Rules = dataclasses.field(default_factory=checking.Rules)  # the user's, with defaults


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
    reasons: str = ""  # why this plan, for the nurse, as the model wrote it


def numbered(csv_text: str) -> tuple[str, list[str]]:
    """The patient list as the model sees it, and the ids: one line per patient, with an id (P1,
    P2, ...) and each cell under its column's name, e.g. "P1: name: Ana; earliest: (empty)".

    The ids let the model name each patient exactly, whatever the list's own columns are. The
    model still reads every cell itself; naming each one, and writing an empty one as (empty),
    only saves it counting commas: given the CSV as it is, it read "...,,12:00" (latest 12:00)
    as earliest 12:00, and a small change anywhere in the prompt could make it do so."""
    table = [row for row in csv.reader(io.StringIO(csv_text.strip())) if any(cell.strip() for cell in row)]
    if len(table) < 2:
        raise ValueError("the patient list needs a header row and at least one patient")
    ids = [f"P{number}" for number in range(1, len(table))]
    header = table[0]
    lines = []
    for patient_id, row in zip(ids, table[1:]):
        cells = []
        for i in range(max(len(header), len(row))):
            name = header[i].strip() if i < len(header) and header[i].strip() else f"column {i + 1}"
            value = " ".join(row[i].split()) if i < len(row) else ""  # one line, whatever the cell holds
            cells.append(f"{name}: {value or '(empty)'}")
        lines.append(f"{patient_id}: {'; '.join(cells)}")
    return "\n".join(lines) + "\n", ids


def shown_window(earliest: str, latest: str) -> str:
    if earliest and latest:
        return f"{earliest}-{latest}"
    if earliest or latest:
        return f"earliest {earliest}" if earliest else f"latest {latest}"
    return "none"


class Agent:
    def __init__(self, request: Request, ask=llm.ask, log=print, find=addresses.find,
                 minutes=travel.walking_minutes):
        self.request, self.ask, self.log, self.find, self.minutes = request, ask, log, find, minutes
        self.patient_list, self.ids = numbered(request.csv_text)
        self.rows = dict(zip(self.ids, self.patient_list.splitlines()))  # to show next to the windows read from them
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
                "all the places you want times for, in one list (patients' ids, and home), e.g. home and every "
                "patient; you get the minutes from each place to each of the others.",
                {"between": {"type": "array", "items": {"type": "string", "enum": [*self.ids, "home"]},
                             "minItems": 2, "maxItems": len(self.ids) + 1}},
                self.travel_times,
            ),
            "best_plans": (
                "best_plans: the best plans by the rules, worked out by trying every plan: the one with the least "
                "walking, the one with the least waiting, and the one home earliest, each with as many visits as "
                "possible. Fill in windows: for every patient on the list, the time window the list gives, earliest "
                "and latest as HH:MM, empty if the list gives none.",
                {"windows": self.windows_field(minimum=len(self.ids))},
                self.best_plans,
            ),
            "check_plan": (
                "check_plan: check a plan before you submit it; it walks through the day in your order and says "
                "the times and any problems. Fill in order: the patients' ids, in visiting order; and windows: for "
                "each patient in order, the time window the patient list gives, earliest and latest as HH:MM, "
                "empty if the list gives none.",
                {"order": {"type": "array", "items": {"type": "string", "enum": self.ids},
                           "minItems": 1, "maxItems": len(self.ids)},
                 "windows": self.windows_field(minimum=0)},
                self.check_plan,
            ),
            "submit_plan": (
                "submit_plan: hand in your plan and finish. Fill in order: the patients' ids, in visiting order; "
                "and reasons: for the nurse, in a sentence or two, why this plan.",
                {"order": {"type": "array", "items": {"type": "string", "enum": self.ids},
                           "minItems": 1, "maxItems": len(self.ids)},
                 "reasons": {"type": "string"}},
                self.submit_plan,
            ),
        }

    def windows_field(self, minimum: int) -> dict:
        """Patients' time windows, as the model read them from the list."""
        return {"type": "array", "minItems": minimum, "maxItems": len(self.ids), "items": {
            "type": "object",
            "properties": {"patient": {"type": "string", "enum": self.ids},
                           "earliest": {"type": "string"}, "latest": {"type": "string"}},
            "required": ["patient", "earliest", "latest"]}}

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
        task = f"{r.rules.describe()} Home: {r.home}.\n\nPatient list:\n{self.patient_list}"
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
        # No times until every place asked about is found: given the others' times, the model went on
        # asking for travel times again and again, and never fixed the address that wasn't found.
        missing = [place for place in asked if place not in self.found]
        if missing:
            return f"Find these addresses first, with find_address: {', '.join(missing)}.", False
        if len(asked) < 2:
            return "Travel times need at least two different places.", False
        minutes = self.minutes([self.found[place] for place in asked])
        lines = ["Walking minutes:"]
        for i, start in enumerate(asked):
            legs = [f"{end} {'no route' if minutes[i][j] is None else minutes[i][j]}"
                    for j, end in enumerate(asked) if j != i]
            lines.append(f"from {start}: {', '.join(legs)}")
        return "\n".join(lines), False

    def best_plans(self, answer: dict) -> tuple[str, bool]:
        places = ["home", *self.ids]
        missing = [place for place in places if place not in self.found]
        if missing:
            return f"Find these addresses first, with find_address: {', '.join(missing)}.", False
        windows = {w["patient"]: (w["earliest"].strip(), w["latest"].strip()) for w in answer["windows"]}
        unread = [patient for patient in self.ids if patient not in windows]
        if unread:
            return (f"Give a window for every patient on the list; missing: {', '.join(unread)}. "
                    "Leave earliest and latest empty where the list gives none."), False
        try:
            found = solving.best_plans(self.ids, windows, self.minutes([self.found[p] for p in places]),
                                       self.request.rules)
        except ValueError as problem:
            return str(problem), False
        # The windows the plans were worked out with, next to the list's own lines, so a misread shows.
        lines = [solving.describe(found), "Windows you gave, next to each patient's line in the list:"]
        lines += [f"{p}: {shown_window(*windows[p])} | list: {self.rows[p]}" for p in self.ids]
        lines.append("If a window is wrong, call best_plans again with it fixed.")
        return "\n".join(lines), False

    def check_plan(self, answer: dict) -> tuple[str, bool]:
        order = answer["order"]
        stops = ["home", *order, "home"]
        missing = [place for place in dict.fromkeys(stops) if place not in self.found]
        if missing:
            return f"Find these addresses first, with find_address: {', '.join(missing)}.", False
        places = list(dict.fromkeys(stops))
        minutes = self.minutes([self.found[place] for place in places])
        legs = [minutes[places.index(start)][places.index(end)] for start, end in zip(stops, stops[1:])]
        windows = {window["patient"]: (window["earliest"], window["latest"]) for window in answer["windows"]}
        return checking.check(order, windows, legs, self.request.rules).text, False

    def submit_plan(self, answer: dict) -> tuple[str, bool]:
        self.order, self.reasons = answer["order"], answer["reasons"]
        return "Plan received.", True

    def run(self) -> Result:
        messages, steps, schema = self.first_messages(), [], self.schema()
        self.order, self.reasons, self.found = [], "", {}
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
                return Result(self.order, steps, "submitted", self.reasons)
        return Result([], steps, "step limit")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv", help="the patient list")
    parser.add_argument("--home", required=True, help="the nurse's home address")
    default = checking.Rules()
    parser.add_argument("--day-start", default=default.day_start, help="leave home at this time at the earliest")
    parser.add_argument("--day-end", default=default.day_end, help="be back home by this time")
    parser.add_argument("--max-visits", type=int, default=default.max_visits)
    parser.add_argument("--visit-minutes", type=int, default=default.visit_minutes, help="how long each visit takes")
    parser.add_argument("--window-slack", type=int, default=default.window_slack_minutes,
                        help="minutes a visit may start before or after the patient's window")
    parser.add_argument("--work-hours", type=float, default=default.work_hours,
                        help="the longest working day, from leaving home to getting back, e.g. 4 or 5.5")
    parser.add_argument("--max-wait", type=int, default=default.max_wait_minutes,
                        help="the longest wait at a patient's door, in minutes")
    args = parser.parse_args()
    rules = checking.Rules(day_start=args.day_start, day_end=args.day_end, max_visits=args.max_visits,
                           visit_minutes=args.visit_minutes, window_slack_minutes=args.window_slack,
                           work_hours=args.work_hours, max_wait_minutes=args.max_wait)
    with open(args.csv, encoding="utf-8") as file:
        request = Request(file.read(), args.home, rules)
    result = Agent(request).run()
    print(f"\n{result.ended} after {len(result.steps)} steps: {' -> '.join(result.order) or 'no plan'}")
    if result.reasons:
        print(f"Why: {result.reasons}")


if __name__ == "__main__":
    main()
