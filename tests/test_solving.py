"""The solver: every plan tried, the best few by different measures."""

import pytest

from homecare.checking import Rules
from homecare.solving import best_plans, describe

TWO_VISITS = Rules(max_visits=2)


def in_seconds(minutes):
    return [[value * 60 for value in row] for row in minutes]


def test_one_plan_best_by_every_measure_is_listed_once():
    # P1 and P2 are next to home and each other; P3 is far from everything.
    minutes = [[0, 1, 2, 9],
               [1, 0, 1, 9],
               [2, 1, 0, 9],
               [9, 9, 9, 0]]
    found = best_plans(["P1", "P2", "P3"], {}, in_seconds(minutes), TWO_VISITS)
    assert (found.visits, found.fitting) == (2, 6)
    assert describe(found) == ("Best plans with 2 visits (6 plans with 2 visits fit the rules):\n"
                               "- least travel (the nurse's preference), tightest group, least waiting, "
                               "earliest home: P1 -> P2: travel 4 min (1 between patients), wait 0 min, "
                               "leave 08:00, back 09:04")


def test_the_least_travel_and_the_earliest_home_can_be_different_plans():
    # P1 can't start before 11:50, P2 not after 08:10. P2 and P3 are 10 minutes apart; all else 1.
    minutes = [[0, 1, 1, 1],
               [1, 0, 1, 1],
               [1, 1, 0, 10],
               [1, 1, 10, 0]]
    found = best_plans(["P1", "P2", "P3"], {"P1": ("12:00", ""), "P2": ("", "08:00")}, in_seconds(minutes), TWO_VISITS)
    # Not P1 or P3 before P2: it would be late. Not P2 then P1: a 189-minute wait at P1's door.
    assert found.fitting == 3
    assert [(plan.measures, plan.order) for plan in found.best] == [
        (["least travel", "tightest group", "least waiting"], ["P3", "P1"]),  # walk 3, leave late, no waiting, back 12:21
        (["earliest home"], ["P2", "P3"])]  # walk 12, leave 08:00, back 09:12
    assert (found.best[1].check.travel, found.best[1].check.back) == (12 * 60, (9 * 60 + 12) * 60)  # seconds


def test_plans_are_compared_in_seconds_not_rounded_minutes():
    # Home to P1 and P2 to home are 40 s; home to P2 and P1 to home are 80 s. In whole minutes
    # (1 each) both orders tie; in seconds P1 then P2 is 80 s shorter.
    seconds = [[0, 40, 80],
               [80, 0, 10],
               [40, 10, 0]]
    found = best_plans(["P1", "P2"], {}, seconds, TWO_VISITS)
    assert found.best[0].order == ["P1", "P2"] and found.best[0].check.travel == 90
    # Seen from the other side, so the order the plans are tried in doesn't decide it.
    found = best_plans(["P2", "P1"], {}, seconds, TWO_VISITS)
    assert found.best[0].order == ["P2", "P1"] and found.best[0].check.travel == 90


def test_the_tightest_group_when_the_nurse_prefers_it():
    # P1 and P2 are next door to each other, 10 minutes from home; P3 is 2 minutes from home.
    minutes = [[0, 10, 10, 2],
               [10, 0, 1, 7],
               [10, 1, 0, 7],
               [2, 6, 7, 0]]
    found = best_plans(["P1", "P2", "P3"], {}, in_seconds(minutes), Rules(max_visits=2, prefer="tightest group"))
    tightest, least_travel = found.best
    # The nurse's preference comes first: P1 and P2, 1 minute apart, 21 minutes in all.
    assert (tightest.order, tightest.measures, tightest.preferred) == (["P1", "P2"], ["tightest group"], True)
    assert (tightest.check.travel, tightest.check.between_patients) == (21 * 60, 60)
    # The least travel goes by P3, near home: 18 minutes in all, but 6 between patients.
    assert (least_travel.order, least_travel.check.travel, least_travel.check.between_patients) == (
        ["P3", "P1"], 18 * 60, 6 * 60)
    assert least_travel.measures[0] == "least travel" and not least_travel.preferred
    assert describe(found).splitlines()[1] == ("- tightest group (the nurse's preference): P1 -> P2: "
                                               "travel 21 min (1 between patients), wait 0 min, leave 08:00, back 09:21")


def test_fewer_visits_when_no_plan_fits_them_all():
    # Both must start by 08:10, and they are an hour apart.
    minutes = [[0, 1, 1],
               [1, 0, 60],
               [1, 60, 0]]
    found = best_plans(["P1", "P2"], {"P1": ("", "08:00"), "P2": ("", "08:00")}, in_seconds(minutes), TWO_VISITS)
    assert (found.visits, found.fitting) == (1, 2)
    assert describe(found).startswith("Best plans with 1 visit (2 plans with 1 visit fit the rules, none with more):")


def test_no_plan_at_all():
    minutes = [[0, 600], [600, 0]]  # ten hours away
    assert describe(best_plans(["P1"], {}, in_seconds(minutes), TWO_VISITS)) == "No plan fits the rules, not even with one visit."


def test_a_time_that_isnt_hh_mm_is_refused():
    with pytest.raises(ValueError, match='P1: "1pm" is not a time written as HH:MM'):
        best_plans(["P1"], {"P1": ("1pm", "")}, [[0, 1], [1, 0]], TWO_VISITS)


def test_a_list_too_long_to_try_every_plan_is_refused():
    with pytest.raises(ValueError, match="up to 12 patients; the list has 13"):
        best_plans([f"P{i}" for i in range(13)], {}, [], TWO_VISITS)
