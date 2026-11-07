"""Run the planner on every case and score it against the answer key.

Each case is scored on separate counts, so a wrong plan shows why it is wrong:
- reading: of the windows the model last gave best_plans, how many are the true ones
- addresses: how many places (home and the patients) it found
- the plan: whether it fits the rules with the true windows; whether it is the best plan by the
  nurse's preference (as many visits as the key, and as little of the preferred measure); and how
  many seconds of that measure it is over the key
- the process: steps, calls wasted (a call repeated, or one a tool refused), how the run ended, time

Results go to evals/results/<date and time>.jsonl, one line per case and run, and a summary is
printed at the end.

Run it (Ollama and the road routers must be running; all the cases take about 12 minutes):
    python -m evals.run
    python -m evals.run --cases bay_ridge --runs 3
"""

import argparse
import dataclasses
import datetime
import json
import pathlib
import time

from homecare import agent, checking
from homecare.solving import MEASURES
from evals.cases import CASES, LISTS, ROOT, Case
from evals.keys import Setting, setting

RESULTS = ROOT / "evals" / "results"

# What a tool answers when it refuses a call: the call was wasted.
REFUSALS = ("Find these addresses first", "Give a window for every patient", "Travel times need at least",
            "is not a time written as HH:MM")


@dataclasses.dataclass
class Score:
    case: str
    run: int
    ended: str  # "submitted", "step limit", or "error: ..."
    order: list[str]
    key_order: list[str]
    visits: int
    key_visits: int
    fits: bool  # no problems with the true windows
    best: bool  # fits, as many visits as the key, and as little of the preferred measure
    extra_seconds: int | None  # of the preferred measure, over the key; None if it doesn't fit or has fewer visits
    problems: list[str]  # with the true windows
    windows_right: int  # of the windows last given to best_plans
    windows_total: int
    misread: dict  # patient: [window given, true window], for each one wrong
    addresses_found: int  # home and the patients
    addresses_total: int
    steps: int
    wasted: int
    actions: list[str]
    seconds_taken: float
    reasons: str


def same_time(given: str, true: str) -> bool:
    """Two times are the same if they are the same minute: "9:00" is "09:00"."""
    if not given.strip() or not true:
        return not given.strip() and not true
    try:
        return checking.minutes(given) == checking.minutes(true)
    except ValueError:
        return False


def windows_read(steps: list[agent.Step]) -> dict[str, tuple[str, str]] | None:
    """The windows the model gave best_plans the last time it called it; None if it never did."""
    calls = [step for step in steps if step.action == "best_plans"]
    if not calls:
        return None
    return {w["patient"]: (w["earliest"], w["latest"]) for w in calls[-1].arguments["windows"]}


def wasted_calls(steps: list[agent.Step]) -> int:
    """Calls that repeat an earlier one exactly, or that a tool refused."""
    seen, wasted = set(), 0
    for step in steps:
        call = (step.action, json.dumps(step.arguments, sort_keys=True))
        if call in seen or any(refusal in step.result for refusal in REFUSALS):
            wasted += 1
        seen.add(call)
    return wasted


def score(s: Setting, run: int, result: agent.Result, found: int, seconds_taken: float) -> Score:
    key = s.key().best[0]
    measure = MEASURES[s.rules.prefer]
    order = result.order
    check = s.check(order) if order else None
    fits = check is not None and not check.problems
    full = fits and len(order) == len(key.order)
    extra = measure(check)[0] - measure(key.check)[0] if full else None

    read = windows_read(result.steps)
    misread = {}
    for patient, true in s.truth.items():
        given = (read or {}).get(patient)
        if given is None or not (same_time(given[0], true[0]) and same_time(given[1], true[1])):
            misread[patient] = [list(given) if given else None, list(true)]

    return Score(
        case=s.case.name, run=run, ended=result.ended, order=order, key_order=key.order,
        visits=len(order), key_visits=len(key.order), fits=fits, best=full and extra <= 0,
        extra_seconds=extra, problems=check.problems if check else ["no plan"],
        windows_right=len(s.truth) - len(misread), windows_total=len(s.truth), misread=misread,
        addresses_found=found, addresses_total=len(s.ids) + 1, steps=len(result.steps),
        wasted=wasted_calls(result.steps), actions=[step.action for step in result.steps],
        seconds_taken=round(seconds_taken, 1), reasons=result.reasons)


def run_case(case: Case, run: int) -> Score:
    s = setting(case)
    request = agent.Request(LISTS[case.patients].text(), case.home, s.rules, case.mode)
    planner = agent.Agent(request, log=lambda *_: None)
    started = time.time()
    try:
        result = planner.run()
    except Exception as problem:  # a failed run is scored as one, not a crash of the whole evaluation
        result = agent.Result([], [], f"error: {problem}")
    return score(s, run, result, len(planner.found), time.time() - started)


def line(sc: Score) -> str:
    verdict = "BEST" if sc.best else ("fits" if sc.fits else "WRONG")
    extra = "" if sc.best or sc.extra_seconds is None else f" (+{sc.extra_seconds} s)"
    fewer = f" ({sc.visits} of {sc.key_visits} visits)" if sc.fits and sc.visits < sc.key_visits else ""
    return (f"{verdict:5} {sc.case}{extra}{fewer}: {' -> '.join(sc.order) or sc.ended}; "
            f"windows {sc.windows_right}/{sc.windows_total}, addresses {sc.addresses_found}/{sc.addresses_total}, "
            f"{sc.steps} steps ({sc.wasted} wasted), {sc.seconds_taken:.0f} s")


def summary(scores: list[Score]) -> str:
    n = len(scores)
    count = lambda test: sum(1 for sc in scores if test(sc))
    windows = sum(sc.windows_right for sc in scores), sum(sc.windows_total for sc in scores)
    return "\n".join([
        f"Runs: {n}",
        f"Best plan: {count(lambda sc: sc.best)}/{n}",
        f"Fits the rules (true windows): {count(lambda sc: sc.fits)}/{n}",
        f"Every window read right: {count(lambda sc: sc.windows_right == sc.windows_total)}/{n} "
        f"({windows[0]}/{windows[1]} windows)",
        f"Every address found: {count(lambda sc: sc.addresses_found == sc.addresses_total)}/{n}",
        f"Submitted: {count(lambda sc: sc.ended == 'submitted')}/{n}",
        f"Steps: {sum(sc.steps for sc in scores) / n:.1f} on average, {sum(sc.wasted for sc in scores)} wasted in all",
        f"Time: {sum(sc.seconds_taken for sc in scores) / n:.0f} s on average",
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", default="", help="only the cases whose name has this in it")
    parser.add_argument("--runs", type=int, default=1, help="runs of each case (the model runs at temperature 0)")
    args = parser.parse_args()
    cases = [case for case in CASES if args.cases in case.name]
    RESULTS.mkdir(exist_ok=True)
    out = RESULTS / f"{datetime.datetime.now():%Y-%m-%d_%H%M}.jsonl"
    scores = []
    with open(out, "w", encoding="utf-8") as file:
        for case in cases:
            for run in range(1, args.runs + 1):
                sc = run_case(case, run)
                scores.append(sc)
                file.write(json.dumps(dataclasses.asdict(sc)) + "\n")
                file.flush()
                print(line(sc), flush=True)
    print(f"\n{summary(scores)}\nResults: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
