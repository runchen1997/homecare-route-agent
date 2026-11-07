"""Find the best plans: try every plan, keep those that break no rule, and pick the best few.

This is the solver in the hybrid design: it works out orders, which a small model does badly,
and the model chooses among the plans it gives, by what the nurse prefers, and explains why.
It gives a few plans, each best by a different measure, rather than one, because which is best
depends on the nurse: the least travel can mean getting home hours later.

It tries every order of up to the most visits allowed, checks each with checking.check, and
keeps the most visits that any plan manages. That is exact, and fast enough for a nurse's list:
for 15 patients and 5 visits it is about 360,000 plans, some 14 seconds.
"""

import dataclasses
import itertools

from homecare import checking

MAX_PATIENTS = 15  # more than this, and trying every plan would take too long (15: about 14 s)

# Each measure: what to make smallest first, then the others to break ties. The nurse's preference
# (Rules.prefer) is one of the first two; best_plans puts it first.
MEASURES = {
    "least travel": lambda check: (check.travel, check.waiting, check.back),
    "tightest group": lambda check: (check.between_patients, check.travel, check.waiting, check.back),
    "least waiting": lambda check: (check.waiting, check.travel, check.back),
    "earliest home": lambda check: (check.back, check.travel, check.waiting),
}


@dataclasses.dataclass
class Best:
    order: list[str]
    check: checking.Check
    measures: list[str]  # the measures this plan is best by
    preferred: bool = False  # best by the measure the nurse prefers


@dataclasses.dataclass
class Found:
    visits: int  # the most visits any plan that fits the rules manages; 0 if none fits
    most_allowed: int  # the most visits the rules and the list allow
    fitting: int  # how many plans with that many visits fit the rules
    best: list[Best]  # the plan best by the nurse's preference first


def best_plans(patients: list[str], windows: dict[str, tuple[str, str]], seconds: list[list[int | None]],
               rules: checking.Rules) -> Found:
    """The best plans with as many visits as possible.

    windows: each patient's (earliest, latest), "" for none; a patient left out has none.
    seconds: travel seconds between the places home, *patients, in that order (None where
    there is no route); plans are compared in seconds, so close ones aren't tied by rounding. Raises ValueError for a list that is too long, or a time that isn't HH:MM."""
    windows = {patient: windows.get(patient, ("", "")) for patient in patients}
    if len(patients) > MAX_PATIENTS:
        raise ValueError(f"best_plans tries every plan, so it works for up to {MAX_PATIENTS} patients; "
                         f"the list has {len(patients)}.")
    for patient, window in windows.items():
        for value in window:
            if value.strip():
                try:
                    checking.minutes(value)
                except ValueError as problem:
                    raise ValueError(f"{patient}: {problem}.") from None

    index = {place: i for i, place in enumerate(["home", *patients])}
    most_allowed = min(rules.max_visits, len(patients))
    for visits in range(most_allowed, 0, -1):
        fitting = []
        for order in itertools.permutations(patients, visits):
            stops = ["home", *order, "home"]
            legs = [seconds[index[start]][index[end]] for start, end in zip(stops, stops[1:])]
            check = checking.check(list(order), windows, legs, rules)
            if not check.problems:
                fitting.append((list(order), check))
        if fitting:
            best: dict[tuple, Best] = {}  # a plan best by several measures is listed once
            measures = [rules.prefer, *(measure for measure in MEASURES if measure != rules.prefer)]
            for measure in measures:
                order, check = min(fitting, key=lambda plan: MEASURES[measure](plan[1]))
                plan = best.setdefault(tuple(order), Best(order, check, [], preferred=measure == rules.prefer))
                plan.measures.append(measure)
            return Found(visits, most_allowed, len(fitting), list(best.values()))
    return Found(0, most_allowed, 0, [])


def describe(found: Found) -> str:
    """The plans found, as the model is told them."""
    if not found.best:
        return "No plan fits the rules, not even with one visit."
    v, n = found.visits, found.fitting
    head = f"Best plans with {v} visit{'s' * (v != 1)} ({n} plan{'s' * (n != 1)} with {v} visit{'s' * (v != 1)} fit the rules"
    head += ", none with more):" if v < found.most_allowed else "):"
    lines = [head]
    for plan in found.best:
        c = plan.check
        measures = list(plan.measures)
        if plan.preferred:  # its first measure is the one the nurse prefers
            measures[0] += " (the nurse's preference)"
        lines.append(f"- {', '.join(measures)}: {' -> '.join(plan.order)}: "
                     f"travel {checking.shown(c.travel)} min ({checking.shown(c.between_patients)} between patients), "
                     f"wait {checking.shown(c.waiting)} min, leave {checking.clock(c.leave)}, back {checking.clock(c.back)}")
    return "\n".join(lines)
