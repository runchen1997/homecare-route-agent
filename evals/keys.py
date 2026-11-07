"""Each case's answer key: the best plans, by trying every plan with the patients' true windows.

The key is the plan best by the nurse's preference (Found.best[0]), with as many visits as any
plan manages. The same places and travel times are kept to check the model's plan against later.

Run it to see every key (the road routers must be running):
    python -m evals.keys
"""

import csv
import dataclasses
import io
import time

from homecare import addresses, checking, solving, travel
from evals.cases import CASES, LISTS, Case


@dataclasses.dataclass
class Setting:
    """What a case's plans are worked out and checked with."""
    case: Case
    ids: list[str]
    truth: dict[str, tuple[str, str]]
    rules: checking.Rules
    seconds: list[list[int | None]]  # travel seconds between home, *ids, in that order

    def check(self, order: list[str]) -> checking.Check:
        """A plan checked against the true windows."""
        index = {place: i for i, place in enumerate(["home", *self.ids])}
        stops = ["home", *order, "home"]
        legs = [self.seconds[index[start]][index[end]] for start, end in zip(stops, stops[1:])]
        return checking.check(order, self.truth, legs, self.rules)

    def key(self) -> solving.Found:
        return solving.best_plans(self.ids, self.truth, self.seconds, self.rules)


def addresses_in(csv_text: str) -> list[str]:
    """Each patient's address as the list writes it: the column named address or where."""
    rows = list(csv.DictReader(io.StringIO(csv_text.strip())))
    column = next(name for name in rows[0] if name.strip().lower() in ("address", "where"))
    return [row[column] for row in rows if any(value.strip() for value in row.values() if value)]


def setting(case: Case, seconds=travel.travel_seconds, find=addresses.find) -> Setting:
    patients = LISTS[case.patients]
    written = addresses_in(patients.text())
    ids = [f"P{i}" for i in range(1, len(written) + 1)]
    places = [find(case.home_address)] + [find(patients.found.get(p, address)) for p, address in zip(ids, written)]
    return Setting(case, ids, patients.truth, checking.Rules(**case.rules), seconds(places, case.mode))


def main() -> None:
    for case in CASES:
        started = time.time()
        found = setting(case).key()
        best = found.best[0]
        c = best.check
        print(f"{case.name}: {found.visits} visits ({found.fitting} plans fit), {best.measures[0]}: "
              f"{' -> '.join(best.order)}; travel {c.travel} s ({c.between_patients} between patients), "
              f"wait {checking.shown(c.waiting)} min, {checking.clock(c.leave)}-{checking.clock(c.back)} "
              f"[{time.time() - started:.1f} s]", flush=True)


if __name__ == "__main__":
    main()
