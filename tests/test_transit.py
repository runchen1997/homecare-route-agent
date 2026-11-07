"""The subway and bus: R5's answers read, and timetables checked for the day planned (no Java needed)."""

import datetime
import zipfile

import pandas
import pytest

from homecare import transit


def test_r5s_minutes_become_seconds_and_no_trip_is_none():
    rows = [(0, 0, 0), (0, 1, 26), (1, 0, float("nan")), (1, 1, pandas.NA)]
    assert transit.table(rows, 2) == [[0, 26 * 60], [None, None]]


def timetable(path, start, end):
    with zipfile.ZipFile(path, "w") as gtfs:
        gtfs.writestr("calendar.txt", "service_id,monday,start_date,end_date\n"
                                      f"weekday,1,{start},20261201\nweekend,0,20261101,{end}\n")
    return path


def test_a_day_the_timetables_dont_run_on_is_refused(tmp_path):
    bus = timetable(tmp_path / "gtfs_b.zip", "20261008", "20270102")
    assert transit.service_dates(bus) == (datetime.date(2026, 10, 8), datetime.date(2027, 1, 2))
    transit.check_dates(datetime.date(2026, 11, 9), [bus])  # runs then: nothing raised
    with pytest.raises(ValueError, match="gtfs_b.zip runs from 2026-10-08 to 2027-01-02, not on 2027-01-04"):
        transit.check_dates(datetime.date(2027, 1, 4), [bus])
