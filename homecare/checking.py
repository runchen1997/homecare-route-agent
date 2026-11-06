"""Check a plan: walk through the nurse's day in the plan's order, and find what breaks the rules.

The checker only says what happens and what is wrong; it never suggests a better order. The
rules are the user's, with defaults, and the same rules are told to the model (Rules.describe),
so the model plans by the rules it is checked against.
"""

import dataclasses
import re


@dataclasses.dataclass
class Rules:
    day_start: str = "08:00"  # the nurse leaves home at this time at the earliest
    day_end: str = "17:00"  # and must be back home by this time
    max_visits: int = 5
    visit_minutes: int = 30
    window_slack_minutes: int = 10  # a visit may start this much before or after the patient's window

    def describe(self) -> str:
        """The rules, as the model is told them."""
        return (f"Tomorrow the nurse leaves home at {self.day_start} at the earliest and must be back by "
                f"{self.day_end}. At most {self.max_visits} visits. Each visit takes {self.visit_minutes} minutes. "
                f"A visit may start up to {self.window_slack_minutes} minutes before the earliest or after the "
                f"latest time in the patient's window; arriving earlier than that, the nurse waits.")


@dataclasses.dataclass
class Check:
    text: str  # the day, step by step, and the problems: what the model is told
    problems: list[str]
    walking: int  # minutes, the whole day
    waiting: int
    leave: int  # leaving home and getting back, in minutes after midnight
    back: int


def minutes(clock_time: str) -> int:
    """Minutes after midnight, from "HH:MM". Raises ValueError for anything else."""
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", clock_time.strip())
    if not match or int(match[1]) > 23 or int(match[2]) > 59:
        raise ValueError(f'"{clock_time}" is not a time written as HH:MM')
    return int(match[1]) * 60 + int(match[2])


def clock(minutes_after_midnight: int) -> str:
    return f"{minutes_after_midnight // 60:02d}:{minutes_after_midnight % 60:02d}"


def check(order: list[str], windows: dict[str, tuple[str, str]], legs: list[int | None], rules: Rules) -> Check:
    """Walk through the day: home, the patients in `order`, home.

    windows: each patient's (earliest, latest) as the model read them from the list, "" for none.
    legs: walking minutes for each leg, home -> first patient, ..., last patient -> home; None if
    there is no route."""
    problems = []
    for patient in dict.fromkeys(order):
        if order.count(patient) > 1:
            problems.append(f"{patient} is in the plan {order.count(patient)} times.")
    if len(order) > rules.max_visits:
        problems.append(f"The plan has {len(order)} visits, more than the limit of {rules.max_visits}.")

    # Each patient's window, in minutes after midnight; None where there is no limit.
    limits = {}
    for patient in order:
        earliest, latest = windows.get(patient, ("", ""))
        if patient not in windows:
            problems.append(f"{patient}: no window given; give earliest and latest, empty if the list has none.")
        limit = []
        for name, value in (("earliest", earliest), ("latest", latest)):
            try:
                limit.append(minutes(value) if value.strip() else None)
            except ValueError as problem:
                problems.append(f"{patient}: could not read the {name} time: {problem}.")
                limit.append(None)
        limits[patient] = tuple(limit)

    slack = rules.window_slack_minutes
    problems += [f"There is no walking route for leg {i + 1} of the day." for i, leg in enumerate(legs) if leg is None]
    legs = [0 if leg is None else leg for leg in legs]  # a missing route is reported above, and counted as 0

    # Leave home just in time for the first visit, but not before the day starts.
    first_earliest = limits[order[0]][0] if order else None
    leave = minutes(rules.day_start)
    if first_earliest is not None:
        leave = max(leave, first_earliest - slack - legs[0])
    lines, now, walked, waited = [f"leave home {clock(leave)}"], leave, 0, 0
    for patient, leg in zip(order, legs):
        earliest, latest = limits[patient]
        arrive = now + leg
        start = arrive if earliest is None else max(arrive, earliest - slack)
        line = f"{patient}: walk {leg} min, arrive {clock(arrive)}"
        if start > arrive:
            line += f", wait {start - arrive} min"
        line += f", start {clock(start)}, finish {clock(start + rules.visit_minutes)}"
        if earliest is not None or latest is not None:
            shown = [clock(limit) if limit is not None else "" for limit in (earliest, latest)]
            line += f" (window {shown[0]}-{shown[1]})"
        if latest is not None and start > latest + slack:
            line += f": LATE, must start by {clock(latest + slack)}"
            problems.append(f"{patient} starts {start - latest - slack} min after its latest start "
                            f"({clock(latest + slack)}).")
        lines.append(line)
        walked, waited, now = walked + leg, waited + start - arrive, start + rules.visit_minutes
    back = now + legs[-1]
    walked += legs[-1]
    lines.append(f"walk {legs[-1]} min, back home {clock(back)}")
    if back > minutes(rules.day_end):
        problems.append(f"Back home at {clock(back)}, after {rules.day_end}.")
    lines.append(f"Total: {len(order)} visit{'s' * (len(order) != 1)}, {walked} min walking, {waited} min waiting.")

    header = "Plan check: OK." if not problems else f"Plan check: {len(problems)} problem{'s' * (len(problems) > 1)}."
    text = "\n".join([header, *lines, *(["Problems:", *(f"- {problem}" for problem in problems)] if problems else [])])
    return Check(text, problems, walked, waited, leave, back)
