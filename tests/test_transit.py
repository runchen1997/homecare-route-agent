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


T = lambda hhmm: datetime.datetime(2026, 11, 9, int(hhmm[:2]), int(hhmm[3:]))
M = lambda minutes: datetime.timedelta(minutes=minutes)


def segment(option, number, mode, departure, travel, **more):
    return {"option": option, "segment": number, "mode": mode, "departure": departure, "travel": travel,
            "wait": more.get("wait", M(0)), "route": more.get("route"), "start_stop": more.get("start"),
            "end_stop": more.get("end"), "line": more.get("line", [[0, 0], [1, 1]])}


def test_the_option_that_arrives_first_is_taken():
    walk_all_the_way = [segment(0, 0, "WALK", None, M(25))]  # leaving 10:00, there at 10:25
    by_train = [segment(1, 0, "WALK", T("10:02"), M(8)),  # the walk to the station, then the train at 10:12
                segment(1, 1, "SUBWAY", T("10:12"), M(6), route="N", start="R16N", end="N02N"),
                segment(1, 2, "WALK", T("10:18"), M(3))]  # there at 10:21
    assert segment(1, 1, "SUBWAY", T("10:12"), M(6), route="N", start="R16N", end="N02N") in \
        transit.quickest(walk_all_the_way + by_train[::-1], T("10:00"))  # in any order
    assert [s["segment"] for s in transit.quickest(walk_all_the_way + by_train, T("10:00"))] == [0, 1, 2]
    slow_bus = [segment(2, 0, "WALK", T("10:05"), M(5)), segment(2, 1, "BUS", T("10:20"), M(10))]  # there 10:30
    assert transit.quickest(walk_all_the_way + slow_bus, T("10:00")) == walk_all_the_way


def test_segments_are_shown_with_route_names_colours_and_stop_names(monkeypatch):
    monkeypatch.setattr(transit, "_names", ({"R16N": "Times Sq-42 St", "N02N": "8 Av"}, {"N": ("N", "#F6BC26", "#000000")}))
    parts = transit.shown([segment(1, 0, "WALK", T("10:02"), M(8)),
                           segment(1, 1, "SUBWAY", T("10:12"), M(6), wait=M(2), route="N", start="N02N", end="R16N")])
    assert parts[0] == {"mode": "walk", "minutes": 8, "line": [[0, 0], [1, 1]]}
    assert parts[1] == {"mode": "subway", "minutes": 6, "line": [[0, 0], [1, 1]], "route": "N", "color": "#F6BC26",
                        "text_color": "#000000", "depart": "10:12", "wait": 2, "start": "8 Av", "end": "Times Sq-42 St"}


def test_a_line_in_several_parts_is_joined_into_one():
    from shapely.geometry import LineString, MultiLineString
    assert transit.points(LineString([(0, 0), (1, 1)])) == [[0, 0], [1, 1]]
    assert transit.points(MultiLineString([[(0, 0), (1, 1)], [(1, 1), (2, 2)]])) == [[0, 0], [1, 1], [2, 2]]
    assert transit.points(None) == [] and transit.points(LineString()) == []


def test_temporary_directories_left_by_earlier_runs_are_removed(tmp_path, monkeypatch):
    import os
    import time
    monkeypatch.setattr(transit, "WORK", tmp_path)
    (tmp_path / "temp" / "r5pyold").mkdir(parents=True)
    (tmp_path / "temp" / "r5pyold" / "streets.osm.pbf").write_text("x")
    (tmp_path / "temp" / "r5pynew").mkdir()
    two_hours_ago = time.time() - 7200
    os.utime(tmp_path / "temp" / "r5pyold", (two_hours_ago, two_hours_ago))
    transit.clear_old_temporary_files()
    assert sorted(p.name for p in (tmp_path / "temp").iterdir()) == ["r5pynew"]



def option(minutes, walk_km, rides=True, walk_minutes=None):
    return {"segments": [], "minutes": minutes, "walk_km": walk_km, "rides": rides,
            "walk_minutes": walk_minutes if walk_minutes is not None else walk_km * 12}


def test_options_added_up_with_their_walking():
    segments = [segment(1, 0, "WALK", T("10:02"), M(8)), segment(1, 1, "BUS", T("10:12"), M(6)),
                segment(0, 0, "WALK", None, M(25))]
    segments[0]["distance"], segments[2]["distance"] = 650.0, 2100.0
    by_bus, walking = sorted(transit.summaries(segments, T("10:00")), key=lambda o: o["rides"], reverse=True)
    assert (by_bus["minutes"], by_bus["walk_km"], by_bus["walk_minutes"], by_bus["rides"]) == (18, 0.65, 8, True)
    assert (walking["minutes"], walking["walk_km"], walking["rides"]) == (25, 2.1, False)


def test_only_options_no_other_beats_on_time_and_walking_are_considered():
    walk, quick_bus, slow_bus, worse = option(28, 2.3, False), option(29, 1.9), option(37, 2.1), option(30, 2.5)
    # The slow bus is slower than the quick one and walks more; "worse" is slower than walking and walks more.
    assert transit.worth_considering([slow_bus, worse, quick_bus, walk]) == [walk, quick_bus]


def test_the_model_judges_whether_the_walking_saved_is_worth_the_minutes():
    walk, bus = option(28, 2.3, False), option(29, 1.9)
    asked = []
    worth = lambda quickest, fewer_km: asked.append((quickest["walk_km"], round(fewer_km, 1))) or 4
    way, why = transit.choose([walk, bus], worth)
    assert way is bus and asked == [(2.3, 0.4)]
    assert why == "1 min longer than the quickest way, 0.4 km less walking: worth up to 4 min to the nurse"
    way, why = transit.choose([walk, option(40, 1.9)], lambda quickest, fewer_km: 4)  # 12 min longer: not worth it
    assert way is walk and why.startswith("The ways with less walking take longer")


def test_with_only_one_way_worth_considering_the_model_isnt_asked():
    def worth(*_):
        raise AssertionError("not asked")
    assert transit.choose([option(31, 1.4), option(33, 2.7, False)], worth) == (option(31, 1.4), "")
