"""The solver: every plan tried, the best few by different measures."""

import pytest

from homecare.checking import Rules
from homecare.solving import best_plans, describe

TWO_VISITS = Rules(max_visits=2)


def test_one_plan_best_by_every_measure_is_listed_once():
    # P1 and P2 are next to home and each other; P3 is far from everything.
    minutes = [[0, 1, 2, 9],
               [1, 0, 1, 9],
               [2, 1, 0, 9],
               [9, 9, 9, 0]]
    found = best_plans(["P1", "P2", "P3"], {}, minutes, TWO_VISITS)
    assert (found.visits, found.fitting) == (2, 6)
    assert describe(found) == ("Best plans with 2 visits (6 plans with 2 visits fit the rules):\n"
                               "- least walking, least waiting, earliest home: P1 -> P2: "
                               "walk 4 min, wait 0 min, leave 08:00, back 09:04")


def test_the_least_walking_and_the_earliest_home_can_be_different_plans():
    # P1 can't start before 11:50, P2 not after 08:10. P2 and P3 are 10 minutes apart; all else 1.
    minutes = [[0, 1, 1, 1],
               [1, 0, 1, 1],
               [1, 1, 0, 10],
               [1, 1, 10, 0]]
    found = best_plans(["P1", "P2", "P3"], {"P1": ("12:00", ""), "P2": ("", "08:00")}, minutes, TWO_VISITS)
    # Not P1 or P3 before P2: it would be late. Not P2 then P1: a 189-minute wait at P1's door.
    assert found.fitting == 3
    assert [(plan.measures, plan.order) for plan in found.best] == [
        (["least walking", "least waiting"], ["P3", "P1"]),  # walk 3, leave late, no waiting, back 12:21
        (["earliest home"], ["P2", "P3"])]  # walk 12, leave 08:00, back 09:12
    assert (found.best[1].check.walking, found.best[1].check.back) == (12, 9 * 60 + 12)


def test_fewer_visits_when_no_plan_fits_them_all():
    # Both must start by 08:10, and they are an hour apart.
    minutes = [[0, 1, 1],
               [1, 0, 60],
               [1, 60, 0]]
    found = best_plans(["P1", "P2"], {"P1": ("", "08:00"), "P2": ("", "08:00")}, minutes, TWO_VISITS)
    assert (found.visits, found.fitting) == (1, 2)
    assert describe(found).startswith("Best plans with 1 visit (2 plans with 1 visit fit the rules, none with more):")


def test_no_plan_at_all():
    minutes = [[0, 600], [600, 0]]  # ten hours away
    assert describe(best_plans(["P1"], {}, minutes, TWO_VISITS)) == "No plan fits the rules, not even with one visit."


def test_a_time_that_isnt_hh_mm_is_refused():
    with pytest.raises(ValueError, match='P1: "1pm" is not a time written as HH:MM'):
        best_plans(["P1"], {"P1": ("1pm", "")}, [[0, 1], [1, 0]], TWO_VISITS)


def test_a_list_too_long_to_try_every_plan_is_refused():
    with pytest.raises(ValueError, match="up to 12 patients; the list has 13"):
        best_plans([f"P{i}" for i in range(13)], {}, [], TWO_VISITS)
