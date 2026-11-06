"""Checking a plan against the rules: 30-minute visits, windows with 10 minutes' slack, by default."""

import pytest

from homecare.checking import Rules, check, clock, minutes

RULES = Rules()


def test_times_are_read_as_hh_mm():
    assert (minutes("08:00"), minutes("9:05"), clock(545)) == (480, 545, "09:05")
    for bad in ["1pm", "noon", "25:00", "12:60"]:
        with pytest.raises(ValueError, match="HH:MM"):
            minutes(bad)


def test_a_plan_without_problems_shows_the_day():
    result = check(["P1", "P2"], {"P1": ("", ""), "P2": ("", "")}, [5, 10, 15], RULES)
    assert result.problems == []
    assert result.text == ("Plan check: OK.\n"
                           "leave home 08:00\n"
                           "P1: walk 5 min, arrive 08:05, start 08:05, finish 08:35\n"
                           "P2: walk 10 min, arrive 08:45, start 08:45, finish 09:15\n"
                           "walk 15 min, back home 09:30\n"
                           "Total: 2 visits, 30 min walking, 0 min waiting.")


def test_the_nurse_leaves_just_in_time_for_the_first_visit():
    result = check(["P1"], {"P1": ("10:00", "")}, [5, 5], RULES)
    assert "leave home 09:45" in result.text  # 10 minutes' slack, 5 minutes' walk
    assert "P1: walk 5 min, arrive 09:50, start 09:50" in result.text


def test_arriving_early_means_waiting_not_a_problem():
    result = check(["P1", "P2"], {"P1": ("", ""), "P2": ("13:00", "")}, [5, 5, 5], RULES)
    assert result.problems == []
    assert "P2: walk 5 min, arrive 08:40, wait 250 min, start 12:50, finish 13:20 (window 13:00-)" in result.text
    assert "250 min waiting" in result.text


def test_starting_within_the_slack_after_the_window_is_fine():
    result = check(["P1"], {"P1": ("", "08:00")}, [10, 10], RULES)
    assert result.problems == []  # starts 08:10, the latest start with 10 minutes' slack


def test_starting_later_than_the_slack_is_a_problem():
    result = check(["P1", "P2"], {"P1": ("13:00", ""), "P2": ("", "12:00")}, [5, 5, 5], RULES)
    assert "P2: walk 5 min, arrive 13:25, start 13:25, finish 13:55 (window -12:00): LATE, must start by 12:10" \
        in result.text
    assert result.problems == ["P2 starts 75 min after its latest start (12:10)."]
    assert result.text.startswith("Plan check: 1 problem.")


def test_too_many_visits_a_patient_twice_and_back_too_late():
    rules = Rules(max_visits=2, day_end="09:00")
    result = check(["P1", "P2", "P1"], {p: ("", "") for p in ["P1", "P2"]}, [5, 5, 5, 5], rules)
    assert result.problems == ["P1 is in the plan 2 times.",
                               "The plan has 3 visits, more than the limit of 2.",
                               "Back home at 09:50, after 09:00."]


def test_windows_the_model_could_not_give_are_problems():
    result = check(["P1", "P2"], {"P1": ("1pm", "")}, [5, 5, 5], RULES)
    assert result.problems == [
        'P1: could not read the earliest time: "1pm" is not a time written as HH:MM.',
        "P2: no window given; give earliest and latest, empty if the list has none."]


def test_a_leg_without_a_route_is_a_problem():
    result = check(["P1"], {"P1": ("", "")}, [None, 5], RULES)
    assert result.problems == ["There is no walking route for leg 1 of the day."]


def test_the_rules_the_model_is_told():
    text = Rules(visit_minutes=45, window_slack_minutes=15).describe()
    assert "Each visit takes 45 minutes." in text and "up to 15 minutes before" in text
