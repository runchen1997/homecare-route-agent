"""Checking a plan against the rules: 30-minute visits, windows with 10 minutes' slack, by default."""

import pytest

from homecare.checking import Rules, check, clock, minutes

RULES = Rules()


def mins(*values):
    """Legs written in minutes, as the seconds check() takes."""
    return [None if value is None else value * 60 for value in values]


def test_times_are_read_as_hh_mm():
    assert (minutes("08:00"), minutes("9:05"), clock(545 * 60)) == (480, 545, "09:05")
    assert clock(545 * 60 + 29) == "09:05" and clock(545 * 60 + 30) == "09:06"  # seconds, to the nearest minute
    for bad in ["1pm", "noon", "25:00", "12:60"]:
        with pytest.raises(ValueError, match="HH:MM"):
            minutes(bad)


def test_a_plan_without_problems_shows_the_day():
    result = check(["P1", "P2"], {"P1": ("", ""), "P2": ("", "")}, mins(5, 10, 15), RULES)
    assert result.problems == []
    assert result.text == ("Plan check: OK.\n"
                           "leave home 08:00\n"
                           "P1: travel 5 min, arrive 08:05, start 08:05, finish 08:35\n"
                           "P2: travel 10 min, arrive 08:45, start 08:45, finish 09:15\n"
                           "travel 15 min, back home 09:30\n"
                           "Total: 2 visits, 30 min travel, 0 min waiting, working day 1 h 30 min.")


def test_each_stop_is_given_as_data_too():
    # P1 must start by 08:10, P2 not before 08:50: leaving 08:05, the nurse waits 5 minutes at P2.
    p1, p2 = check(["P1", "P2"], {"P1": ("", "08:00"), "P2": ("09:00", "")}, mins(5, 5, 5), RULES).stops
    assert (p1.patient, p1.travel, clock(p1.arrive), p1.wait, clock(p1.start), clock(p1.finish)) == (
        "P1", 300, "08:10", 0, "08:10", "08:40")  # seconds
    assert (p2.patient, clock(p2.arrive), p2.wait, clock(p2.start), p2.earliest, p2.latest, p2.late) == (
        "P2", "08:45", 300, "08:50", 9 * 3600, None, False)
    # The other way round, P1 starts 09:25, late.
    _, p1 = check(["P2", "P1"], {"P1": ("", "08:00"), "P2": ("09:00", "")}, mins(5, 5, 5), RULES).stops
    assert (p1.patient, clock(p1.start), p1.late) == ("P1", "09:25", True)


def test_travel_between_patients_leaves_out_home():
    result = check(["P1", "P2", "P3"], {}, mins(10, 1, 2, 12), RULES)
    assert (result.travel, result.between_patients) == (25 * 60, 3 * 60)
    assert check([], {}, mins(0), RULES).between_patients == 0


def test_a_rule_broken_by_seconds_shows_as_at_least_a_minute():
    # P1 must start by 08:10; 10 min 20 s away, leaving 08:00 at the earliest: 20 seconds late.
    result = check(["P1"], {"P1": ("", "08:00")}, [620, 620], RULES)
    assert result.problems == ["P1 starts 1 min after its latest start (08:10)."]
    assert result.stops[0].late


def test_the_nurse_leaves_just_in_time_for_the_first_visit():
    result = check(["P1"], {"P1": ("10:00", "")}, mins(5, 5), RULES)
    assert "leave home 09:45" in result.text  # 10 minutes' slack, 5 minutes' walk
    assert "P1: travel 5 min, arrive 09:50, start 09:50" in result.text


def test_the_nurse_waits_at_home_rather_than_at_a_door():
    # Leaving at 08:00 would mean waiting 250 minutes at P2; leaving later, P1 still has no window.
    result = check(["P1", "P2"], {"P1": ("", ""), "P2": ("13:00", "")}, mins(5, 5, 5), RULES)
    assert result.text.splitlines()[1:4] == ["leave home 12:10",
                                             "P1: travel 5 min, arrive 12:15, start 12:15, finish 12:45",
                                             "P2: travel 5 min, arrive 12:50, start 12:50, finish 13:20 (window 13:00-)"]


def test_a_wait_that_cant_be_avoided_counts_against_the_longest_wait():
    # P1 must start by 08:40, P2 not before 12:50: the nurse waits between them.
    result = check(["P1", "P2"], {"P1": ("", "08:30"), "P2": ("13:00", "")}, mins(5, 5, 5), RULES)
    assert "leave home 08:35" in result.text  # as late as P1 allows
    assert ("P2: travel 5 min, arrive 09:15, wait 215 min (longer than 20), start 12:50, finish 13:20 (window 13:00-)"
            in result.text)
    assert "215 min waiting, working day 4 h 50 min." in result.text
    assert result.problems == ["P2: waits 215 min at the door, more than the 20 min allowed."]
    assert check(["P1", "P2"], {"P1": ("", "08:30"), "P2": ("13:00", "")}, mins(5, 5, 5),
                 Rules(max_wait_minutes=None)).problems == []


def test_a_wait_up_to_the_longest_is_fine():
    # P1 must start by 08:40 and finishes 09:10; P2 can start from 09:30, 20 minutes after arriving.
    result = check(["P1", "P2"], {"P1": ("", "08:30"), "P2": ("09:40", "")}, mins(5, 0, 5), RULES)
    assert "wait 20 min, start 09:30" in result.text
    assert result.problems == []


def test_a_working_day_longer_than_allowed_is_a_problem():
    rules = Rules(work_hours=4.5, max_wait_minutes=None)
    result = check(["P1", "P2"], {"P1": ("", "08:30"), "P2": ("13:00", "")}, mins(5, 5, 5), rules)
    assert result.problems == ["The working day is 4 h 50 min, longer than 4 h 30 min."]
    assert "The working day, from leaving home to getting back, is at most 4 h 30 min." in rules.describe()


def test_starting_within_the_slack_after_the_window_is_fine():
    result = check(["P1"], {"P1": ("", "08:00")}, mins(10, 10), RULES)
    assert result.problems == []  # starts 08:10, the latest start with 10 minutes' slack


def test_starting_later_than_the_slack_is_a_problem():
    result = check(["P1", "P2"], {"P1": ("13:00", ""), "P2": ("", "12:00")}, mins(5, 5, 5), RULES)
    assert "P2: travel 5 min, arrive 13:25, start 13:25, finish 13:55 (window -12:00): LATE, must start by 12:10" \
        in result.text
    assert result.problems == ["P2 starts 75 min after its latest start (12:10)."]
    assert result.text.startswith("Plan check: 1 problem.")


def test_too_many_visits_a_patient_twice_and_back_too_late():
    rules = Rules(max_visits=2, day_end="09:00")
    result = check(["P1", "P2", "P1"], {p: ("", "") for p in ["P1", "P2"]}, mins(5, 5, 5, 5), rules)
    assert result.problems == ["P1 is in the plan 2 times.",
                               "The plan has 3 visits, more than the limit of 2.",
                               "Back home at 09:50, after 09:00."]


def test_windows_the_model_could_not_give_are_problems():
    result = check(["P1", "P2"], {"P1": ("1pm", "")}, mins(5, 5, 5), RULES)
    assert result.problems == [
        'P1: could not read the earliest time: "1pm" is not a time written as HH:MM.',
        "P2: no window given; give earliest and latest, empty if the list has none."]


def test_a_leg_without_a_route_is_a_problem():
    result = check(["P1"], {"P1": ("", "")}, mins(None, 5), RULES)
    assert result.problems == ["There is no route for leg 1 of the day."]


def test_the_rules_the_model_is_told():
    text = Rules(visit_minutes=45, window_slack_minutes=15).describe()
    assert "Each visit takes 45 minutes." in text and "up to 15 minutes before" in text
    assert "At most 20 minutes of waiting at any patient's door." in text
