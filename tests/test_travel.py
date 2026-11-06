"""Travel times from the road router, with a stand-in for its web service."""

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


def test_seconds_become_whole_minutes(monkeypatch):
    asked = answer_with(monkeypatch, {"code": "Ok", "durations": [[0, 389.6], [410.2, None]]})
    assert travel.travel_minutes(PLACES) == [[0, 6], [7, None]]  # None: no route
    # Longitude comes first, and one request asks for every pair.
    assert asked == ["http://localhost:5001/table/v1/foot/-73.98,40.62;-73.99,40.61?annotations=duration"]


def test_a_refused_request_says_why(monkeypatch):
    body = io.BytesIO(b'{"code": "TooBig", "message": "Too many table coordinates"}')
    answer_with(monkeypatch, problem=urllib.error.HTTPError("url", 400, "Bad Request", {}, body))
    with pytest.raises(ValueError, match="Too many table coordinates"):
        travel.travel_minutes(PLACES)


def test_a_router_that_is_not_running(monkeypatch):
    answer_with(monkeypatch, problem=urllib.error.URLError("connection refused"))
    with pytest.raises(ConnectionError, match="docker compose up -d"):
        travel.travel_minutes(PLACES)


def test_each_way_of_travelling_has_its_own_router(monkeypatch):
    asked = answer_with(monkeypatch, {"code": "Ok", "durations": [[0, 60], [60, 0]]})
    assert travel.travel_minutes(PLACES, "driving") == [[0, 1], [1, 0]]
    assert asked[0].startswith("http://localhost:5000/table/v1/car/")
    with pytest.raises(ValueError, match='no way of travelling called "flying"; there are walking, driving'):
        travel.travel_minutes(PLACES, "flying")
