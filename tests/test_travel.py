"""Travel times from the road router, with a stand-in for its web service."""

import datetime
import io
import json
import urllib.error

import pytest

from homecare import travel
from homecare.addresses import Place

PLACES = [Place("home", 40.62, -73.98), Place("P1", 40.61, -73.99)]


def answer_with(monkeypatch, reply=None, problem=None):
    """Make the road router give `reply` (as JSON), or raise `problem`; keep the URLs asked for."""
    asked = []

    def urlopen(url, timeout):
        asked.append(url)
        if problem:
            raise problem
        return io.BytesIO(json.dumps(reply).encode())

    monkeypatch.setattr(travel.urllib.request, "urlopen", urlopen)
    return asked


def test_travel_times_are_whole_seconds(monkeypatch):
    asked = answer_with(monkeypatch, {"code": "Ok", "durations": [[0, 389.6], [410.2, None]]})
    assert travel.travel_seconds(PLACES) == [[0, 390], [410, None]]  # None: no route
    # Longitude comes first, and one request asks for every pair.
    assert asked == ["http://localhost:5001/table/v1/foot/-73.98,40.62;-73.99,40.61?annotations=duration"]


def test_a_refused_request_says_why(monkeypatch):
    body = io.BytesIO(b'{"code": "TooBig", "message": "Too many table coordinates"}')
    answer_with(monkeypatch, problem=urllib.error.HTTPError("url", 400, "Bad Request", {}, body))
    with pytest.raises(ValueError, match="Too many table coordinates"):
        travel.travel_seconds(PLACES)


def test_a_router_that_is_not_running(monkeypatch):
    answer_with(monkeypatch, problem=urllib.error.URLError("connection refused"))
    with pytest.raises(ConnectionError, match="docker compose up -d"):
        travel.travel_seconds(PLACES)


def test_each_way_of_travelling_has_its_own_router(monkeypatch):
    asked = answer_with(monkeypatch, {"code": "Ok", "durations": [[0, 60], [60, 0]]})
    assert travel.travel_seconds(PLACES, "driving") == [[0, 60], [60, 0]]
    assert asked[0].startswith("http://localhost:5000/table/v1/car/")
    with pytest.raises(ValueError, match='no way of travelling called "flying"; there are walking, driving'):
        travel.travel_seconds(PLACES, "flying")


def test_a_route_is_one_line_of_points_per_leg(monkeypatch):
    leg = lambda *steps: {"steps": [{"geometry": {"coordinates": points}} for points in steps]}
    asked = answer_with(monkeypatch, {"code": "Ok", "routes": [{"legs": [
        leg([[-73.98, 40.62], [-73.985, 40.615]], [[-73.985, 40.615], [-73.99, 40.61]]),
        leg([[-73.99, 40.61], [-73.98, 40.62]])]}]})
    home_p1_home = PLACES + PLACES[:1]
    assert travel.route(home_p1_home) == [
        [[-73.98, 40.62], [-73.985, 40.615], [-73.99, 40.61]],  # a point where two steps meet is kept once
        [[-73.99, 40.61], [-73.98, 40.62]]]
    assert asked == ["http://localhost:5001/route/v1/foot/-73.98,40.62;-73.99,40.61;-73.98,40.62"
                     "?overview=false&steps=true&geometries=geojson"]



def test_by_subway_and_bus_the_times_come_from_r5_for_the_working_day(monkeypatch):
    from homecare import transit
    asked = []
    monkeypatch.setattr(transit, "travel_seconds", lambda places, day: asked.append(day) or [[0, 600], [660, 0]])
    day = travel.working_day(datetime.date(2026, 11, 9), "09:00", "16:00")
    assert travel.travel_seconds(PLACES, "transit", day) == [[0, 600], [660, 0]]
    assert asked == [(datetime.datetime(2026, 11, 9, 9, 0), datetime.datetime(2026, 11, 9, 16, 0))]
    assert "transit" in travel.ALL_MODES


def test_by_subway_and_bus_the_route_is_a_straight_line_for_now():
    assert travel.route(PLACES, "transit") == [[[-73.98, 40.62], [-73.99, 40.61]]]
