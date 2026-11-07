"""Check a plan: walk through the nurse's day in the plan's order, and find what breaks the rules.

The checker only says what happens and what is wrong; it never suggests a better order. The
rules are the user's, with defaults, and the same rules are told to the model (Rules.describe),
so the model plans by the rules it is checked against.
"""

import dataclasses
import re
from typing import Literal

# What the nurse prefers among plans with as many visits: as the model is told it.
PREFERENCES = {
    "least travel": "the least travel in the whole day, from leaving home to getting back",
    "tightest group": ("the tightest group of patients: the least travel between patients (leaving out the "
                       "trips from home and back), then the least travel in the whole day"),
}


@dataclasses.dataclass
class Rules:
    day_start: str = "08:00"  # the nurse leaves home at this time at the earliest
    day_end: str = "17:00"  # and must be back home by this time
    max_visits: int = 5
    visit_minutes: int = 30
    window_slack_minutes: int = 10  # a visit may start this much before or after the patient's window
    work_hours: float | None = None  # the longest working day, from leaving home to getting back; None: no limit
    max_wait_minutes: int | None = 20  # the longest wait at a patient's door; None: no limit
    prefer: Literal[tuple(PREFERENCES)] = "least travel"  # among plans with as many visits, which is best

    def describe(self) -> str:
        """The rules, as the model is told them."""
        text = (f"Tomorrow the nurse leaves home at {self.day_start} at the earliest and must be back by "
                f"{self.day_end}. At most {self.max_visits} visits. Each visit takes {self.visit_minutes} minutes. "
                f"A visit may start up to {self.window_slack_minutes} minutes before the earliest or after the "
                f"latest time in the patient's window; arriving earlier than that, the nurse waits. The nurse "
                f"leaves home as late as the plan allows, so waits at home rather than at a door where possible.")
        if self.work_hours is not None:
            text += (f" The working day, from leaving home to getting back, is at most "
                     f"{duration(round(self.work_hours * 3600))}.")
        if self.max_wait_minutes is not None:
            text += f" At most {self.max_wait_minutes} minutes of waiting at any patient's door."
        text += f" Among plans with as many visits, the nurse prefers {PREFERENCES[self.prefer]}."
        return text


@dataclasses.dataclass
class Stop:
    """One visit in the day, for showing the plan; times in seconds after midnight."""
    patient: str
    travel: int  # seconds from the place before
    arrive: int
    start: int
    finish: int
    earliest: int | None  # the patient's window as given; None where there is no limit
    latest: int | None
    late: bool  # starts later than the window and its slack allow

    @property
    def wait(self) -> int:
        return self.start - self.arrive


@dataclasses.dataclass
class Check:
    """A plan walked through. Times are whole seconds, so that plans compare exactly; the text shows
    them in minutes."""
    text: str  # the day, step by step, and the problems: what the model is told
    problems: list[str]
    travel: int  # seconds travelling, the whole day
    waiting: int
    leave: int  # leaving home and getting back, in seconds after midnight
    back: int
    stops: list[Stop]  # each visit, in order

    @property
    def between_patients(self) -> int:
        """Seconds travelling from one patient to the next, leaving out the trips from home and back."""
        if not self.stops:
            return 0
        return self.travel - self.stops[0].travel - (self.back - self.stops[-1].finish)


def minutes(clock_time: str) -> int:
    """Minutes after midnight, from "HH:MM". Raises ValueError for anything else."""
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", clock_time.strip())
    if not match or int(match[1]) > 23 or int(match[2]) > 59:
        raise ValueError(f'"{clock_time}" is not a time written as HH:MM')
    return int(match[1]) * 60 + int(match[2])


def shown(seconds: int) -> int:
    """Seconds as whole minutes, to the nearest one: how times are shown."""
    return (seconds + 30) // 60


def over(seconds: int) -> int:
    """Seconds as whole minutes, rounded up: how much a rule is broken by, so it never shows as 0."""
    return -(-seconds // 60)


def clock(seconds_after_midnight: int) -> str:
    hours, rest = divmod(shown(seconds_after_midnight), 60)
    return f"{hours:02d}:{rest:02d}"


def duration(seconds: int) -> str:
    hours, rest = divmod(shown(seconds), 60)
    return f"{hours} h {rest} min" if hours else f"{rest} min"


def check(order: list[str], windows: dict[str, tuple[str, str]], legs: list[int | None], rules: Rules) -> Check:
    """Walk through the day: home, the patients in `order`, home.

    windows: each patient's (earliest, latest) as the model read them from the list, "" for none.
    legs: travel seconds for each leg, home -> first patient, ..., last patient -> home; None if
    there is no route."""
    problems = []
    for patient in dict.fromkeys(order):
        if order.count(patient) > 1:
            problems.append(f"{patient} is in the plan {order.count(patient)} times.")
    if len(order) > rules.max_visits:
        problems.append(f"The plan has {len(order)} visits, more than the limit of {rules.max_visits}.")

    # Each patient's window, in seconds after midnight; None where there is no limit.
    limits = {}
    for patient in order:
        earliest, latest = windows.get(patient, ("", ""))
        if patient not in windows:
            problems.append(f"{patient}: no window given; give earliest and latest, empty if the list has none.")
        limit = []
        for name, value in (("earliest", earliest), ("latest", latest)):
            try:
                limit.append(minutes(value) * 60 if value.strip() else None)
            except ValueError as problem:
                problems.append(f"{patient}: could not read the {name} time: {problem}.")
                limit.append(None)
        limits[patient] = tuple(limit)

    # The rules, in seconds.
    slack, visit = rules.window_slack_minutes * 60, rules.visit_minutes * 60
    day_start, day_end = minutes(rules.day_start) * 60, minutes(rules.day_end) * 60
    longest_day = None if rules.work_hours is None else round(rules.work_hours * 3600)
    longest_wait = None if rules.max_wait_minutes is None else rules.max_wait_minutes * 60
    problems += [f"There is no route for leg {i + 1} of the day." for i, leg in enumerate(legs) if leg is None]
    legs = [0 if leg is None else leg for leg in legs]  # a missing route is reported above, and counted as 0

    def day(leave: int) -> tuple[list[tuple[int, int]], int]:
        """Each visit's arrival and start, leaving home at `leave`; and the time back home."""
        visits, now = [], leave
        for patient, leg in zip(order, legs):
            earliest = limits[patient][0]
            arrive = now + leg
            start = arrive if earliest is None else max(arrive, earliest - slack)
            visits.append((arrive, start))
            now = start + visit
        return visits, now + legs[-1]

    # Leave home as late as possible: waiting at home, not at a door. Leaving `shift` seconds after
    # the day starts moves each visit's start by what is left of the shift after the waiting before
    # it; so leave no later than lets every visit start within its window (or no later than it
    # would anyway), and no later than the waiting in the whole day, or the nurse gets home later.
    visits, _ = day(day_start)
    shift, waited_so_far = None, 0
    for patient, (arrive, start) in zip(order, visits):
        waited_so_far += start - arrive
        latest = limits[patient][1]
        if latest is not None:
            room = max(latest + slack - start, 0) + waited_so_far
            shift = room if shift is None else min(shift, room)
    shift = waited_so_far if shift is None else min(shift, waited_so_far)
    leave = day_start + shift
    visits, back = day(leave)

    lines, stops, travelled, waited = [f"leave home {clock(leave)}"], [], 0, 0
    for patient, leg, (arrive, start) in zip(order, legs, visits):
        earliest, latest = limits[patient]
        wait = start - arrive
        line = f"{patient}: travel {shown(leg)} min, arrive {clock(arrive)}"
        if longest_wait is not None and wait > longest_wait:
            line += f", wait {over(wait)} min (longer than {rules.max_wait_minutes})"
            problems.append(f"{patient}: waits {over(wait)} min at the door, more than the "
                            f"{rules.max_wait_minutes} min allowed.")
        elif shown(wait) > 0:
            line += f", wait {shown(wait)} min"
        line += f", start {clock(start)}, finish {clock(start + visit)}"
        if earliest is not None or latest is not None:
            limit_text = [clock(limit) if limit is not None else "" for limit in (earliest, latest)]
            line += f" (window {limit_text[0]}-{limit_text[1]})"
        late = latest is not None and start > latest + slack
        if late:
            line += f": LATE, must start by {clock(latest + slack)}"
            problems.append(f"{patient} starts {over(start - latest - slack)} min after its latest start "
                            f"({clock(latest + slack)}).")
        lines.append(line)
        stops.append(Stop(patient, leg, arrive, start, start + visit, earliest, latest, late))
        travelled, waited = travelled + leg, waited + wait
    travelled += legs[-1]
    lines.append(f"travel {shown(legs[-1])} min, back home {clock(back)}")
    if back > day_end:
        problems.append(f"Back home at {clock(back)}, after {rules.day_end}.")
    if longest_day is not None and back - leave > longest_day:
        problems.append(f"The working day is {duration(back - leave)}, longer than {duration(longest_day)}.")
    lines.append(f"Total: {len(order)} visit{'s' * (len(order) != 1)}, {shown(travelled)} min travel, "
                 f"{shown(waited)} min waiting, working day {duration(back - leave)}.")

    header = "Plan check: OK." if not problems else f"Plan check: {len(problems)} problem{'s' * (len(problems) > 1)}."
    text = "\n".join([header, *lines, *(["Problems:", *(f"- {problem}" for problem in problems)] if problems else [])])
    return Check(text, problems, travelled, waited, leave, back, stops)
