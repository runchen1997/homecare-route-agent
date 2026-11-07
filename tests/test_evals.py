"""The evaluation cases: each list's true windows line up with the patients the model is shown."""

from homecare import agent, checking, travel
from homecare.addresses import Place
from evals.cases import CASES, LISTS
from evals.keys import addresses_in, setting
from evals.run import same_time, score


def test_every_list_has_a_true_window_for_each_patient_the_model_sees():
    for name, patients in LISTS.items():
        _, ids = agent.numbered(patients.text())
        assert list(patients.truth) == ids, name
        assert len(addresses_in(patients.text())) == len(ids), name
        for earliest, latest in patients.truth.values():
            for value in (earliest, latest):
                if value:
                    checking.minutes(value)  # HH:MM, or this raises


def test_every_case_names_a_list_and_rules_that_exist():
    assert len({case.name for case in CASES}) == len(CASES)
    for case in CASES:
        assert case.patients in LISTS, case.name
        checking.Rules(**case.rules)  # every rule named is a rule
        assert case.mode in travel.ALL_MODES, case.name


def test_a_plan_is_checked_against_the_true_windows():
    case = next(case for case in CASES if case.name == "messy")
    seen = []

    def find(address):
        seen.append(address)
        return Place(address, 40.6, -74.0)

    s = setting(case, seconds=lambda places, mode, day: [[0 if a is b else 300 for b in places] for a in places], find=find)
    assert seen[0] == "1025 70th St, Brooklyn" and len(seen) == 9  # home, then the 8 patients as written
    # True windows: P2 by 12:00, P3 from 13:00 (each with 10 minutes' slack). P2 first, then P3: the
    # nurse leaves late enough not to wait at P3's door, and P2 is still on time.
    assert s.check(["P2", "P1", "P3"]).problems == []
    # P3 first can't start before 12:50, so P2 after it is late.
    assert any(problem.startswith("P2 starts") for problem in s.check(["P3", "P2"]).problems)


def test_an_address_the_list_writes_another_way_is_found_as_the_key_says():
    case = next(case for case in CASES if case.patients == "bay_ridge_messy")
    seen = []
    setting(case, seconds=lambda places, mode, day: [[0] * len(places)] * len(places),
            find=lambda address: seen.append(address) or Place(address, 40.6, -74.0))
    assert seen[4] == "6901 3rd Ave, Brooklyn"  # P4: "6901 Third Avenue, Bay Ridge" in the list


def scripted_run(order, windows, extra_steps=()):
    """An agent's result: best_plans called with `windows`, then the plan handed in."""
    best = agent.Step("best", "best_plans", {"windows": [{"patient": p, "earliest": e, "latest": l}
                                                         for p, (e, l) in windows.items()]}, "Best plans ...")
    steps = [*extra_steps, best, agent.Step("done", "submit_plan", {"order": order, "reasons": "r"}, "Plan received.")]
    return agent.Result(order, steps, "submitted", "r")


def messy_setting():
    case = next(case for case in CASES if case.name == "messy")
    # Five minutes between any two places, except P8, an hour from everywhere.
    def seconds(places, mode, day):
        return [[0 if a is b else (3600 if 8 in (i, j) else 300) for j, b in enumerate(places)]
                for i, a in enumerate(places)]
    return setting(case, seconds=seconds, find=lambda address: Place(address, 40.6, -74.0))


def test_the_best_plan_and_windows_read_right_score_full_marks():
    s = messy_setting()
    key = s.key().best[0]
    sc = score(s, 1, scripted_run(key.order, s.truth), found=9, seconds_taken=20.0)
    assert (sc.best, sc.fits, sc.extra_seconds, sc.windows_right, sc.windows_total) == (True, True, 0, 8, 8)
    assert (sc.addresses_found, sc.addresses_total, sc.steps, sc.wasted) == (9, 9, 2, 0)


def test_a_misread_window_and_a_worse_plan_are_scored_apart():
    s = messy_setting()
    key = s.key().best[0]
    # P2 read as earliest 12:00, not latest: wrong, while the plan is still worked out.
    windows = {**s.truth, "P2": ("12:00", "")}
    worse = [p for p in key.order if p != key.order[-1]] + ["P8"]  # P8, an hour away, for the last visit
    sc = score(s, 1, scripted_run(worse, windows), found=9, seconds_taken=20.0)
    assert sc.misread == {"P2": [["12:00", ""], ["", "12:00"]]} and sc.windows_right == 7
    assert sc.fits and not sc.best and sc.extra_seconds > 0


def test_a_plan_late_by_the_true_windows_does_not_fit():
    s = messy_setting()
    sc = score(s, 1, scripted_run(["P3", "P2"], s.truth), found=9, seconds_taken=1.0)
    assert not sc.fits and not sc.best and sc.extra_seconds is None
    assert any(problem.startswith("P2 starts") for problem in sc.problems)


def test_repeated_and_refused_calls_are_wasted():
    s = messy_setting()
    look = agent.Step("t", "find_address", {"places": [{"place": "home", "address": "x"}]}, "home: found x")
    refused = agent.Step("t", "travel_times", {"between": ["home", "P1"]}, "Find these addresses first, with find_address: P1.")
    sc = score(s, 1, scripted_run(s.key().best[0].order, s.truth, [look, look, refused]), found=9, seconds_taken=1.0)
    assert sc.wasted == 2 and sc.steps == 5


def test_times_are_compared_by_the_minute():
    assert same_time("9:00", "09:00") and same_time(" ", "") and not same_time("9am", "09:00")
    assert not same_time("", "09:00")
