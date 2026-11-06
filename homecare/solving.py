"""Find the best plans: try every plan, keep those that break no rule, and pick the best few.

This is the solver in the hybrid design: it works out orders, which a small model does badly,
and the model chooses among the plans it gives, by what the nurse prefers, and explains why.
It gives a few plans, each best by a different measure, rather than one, because which is best
depends on the nurse: the least walking can mean hours of waiting in the middle of the day.

It tries every order of up to the most visits allowed, checks each with checking.check, and
keeps the most visits that any plan manages. That is exact, and fast enough for a nurse's list:
for 12 patients and 5 visits it is about 95,000 plans.
"""

import dataclasses
import itertools

from homecare import checking

MAX_PATIENTS = 12  # more than this, and trying every plan would take too long

# Each measure: what to make smallest first, then the others to break ties.
MEASURES = {
    "least walking": lambda check: (check.walking, check.waiting, check.back),
    "least waiting": lambda check: (check.waiting, check.walking, check.back),
    "earliest home": lambda check: (check.back, check.walking, check.waiting),
}


@dataclasses.dataclass
class Best:
    order: list[str]
    check: checking.Check
    measures: list[str]  # the measures this plan is best by


@dataclasses.dataclass
class Found:
    visits: int  # the most visits any plan that fits the rules manages; 0 if none fits
    most_allowed: int  # the most visits the rules and the list allow
    fitting: int  # how many plans with that many visits fit the rules
    best: list[Best]


def best_plans(patients: list[str], windows: dict[str, tuple[str, str]], minutes: list[list[int | None]],
               rules: checking.Rules) -> Found:
    """The best plans with as many visits as possible.

    windows: each patient's (earliest, latest), "" for none; a patient left out has none.
    minutes: walking minutes between the places home, *patients, in that order (None where
    there is no route). Raises ValueError for a list that is too long, or a time that isn't HH:MM."""
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
            legs = [minutes[index[start]][index[end]] for start, end in zip(stops, stops[1:])]
            check = checking.check(list(order), windows, legs, rules)
            if not check.problems:
                fitting.append((list(order), check))
        if fitting:
            best: dict[tuple, Best] = {}  # a plan best by several measures is listed once
            for measure, key in MEASURES.items():
                order, check = min(fitting, key=lambda plan: key(plan[1]))
                best.setdefault(tuple(order), Best(order, check, [])).measures.append(measure)
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
        lines.append(f"- {', '.join(plan.measures)}: {' -> '.join(plan.order)}: walk {c.walking} min, "
                     f"wait {c.waiting} min, leave {checking.clock(c.leave)}, back {checking.clock(c.back)}")
    return "\n".join(lines)
