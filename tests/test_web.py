"""The web service, with stand-ins for the model, the address index and the road routers."""

import json

from fastapi.testclient import TestClient

from homecare.addresses import AddressError, Place
from homecare.web import create_app

CSV = "name,address,latest\nAna,1 A St,09:00\nBo,2 B St,\n"
PLACES = {"1 A St": Place("1 A Street, Brooklyn 11201", 40.1, -73.1),
          "2 B St": Place("2 B Street, Brooklyn 11201", 40.2, -73.2),
          "9 Home St": Place("9 Home Street, Brooklyn 11209", 40.9, -73.9)}


def find(address):
    if address not in PLACES:
        raise AddressError(f'not found: no street called "{address}"')
    return PLACES[address]


def seconds(places, mode, day=None):
    """Five minutes between any two different places."""
    return [[0 if a == b else 300 for b in places] for a in places]


def route(places, mode):
    """A straight line for each leg."""
    return [[[a.lon, a.lat], [b.lon, b.lat]] for a, b in zip(places, places[1:])]


def scripted(*answers):
    replies = iter(answers)
    return lambda messages, schema, max_tokens: next(replies)


def events(response):
    """The (event, data) pairs in a stream of Server-Sent Events."""
    pairs = []
    for block in response.text.strip().split("\n\n"):
        name, data = block.split("\n")
        pairs.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return pairs


def post(app, **request):
    return TestClient(app).post("/api/plan", json={"csv": CSV, "home": "9 Home St", **request})


LOOK_UP = {"thinking": "where?", "action": "find_address",
           "places": [{"place": "P1", "address": "1 A St"}, {"place": "P2", "address": "2 B St"},
                      {"place": "home", "address": "9 Home St"}]}
BEST = {"thinking": "best?", "action": "best_plans",
        "windows": [{"patient": "P1", "earliest": "", "latest": "09:00"},
                    {"patient": "P2", "earliest": "", "latest": ""}]}
SUBMIT = {"thinking": "done", "action": "submit_plan", "order": ["P1", "P2"], "reasons": "P1 must be early"}


def test_each_step_then_the_plan_with_its_schedule_and_route():
    app = create_app(scripted(LOOK_UP, BEST, SUBMIT), find, seconds, route)
    response = post(app, mode="driving", rules={"max_visits": 2, "prefer": "tightest group"})
    assert response.headers["content-type"].startswith("text/event-stream")
    sent = events(response)
    assert [name for name, _ in sent] == ["step", "step", "step", "plan"]
    assert sent[0][1]["number"] == 1 and sent[0][1]["action"] == "find_address"
    assert sent[0][1]["result"].startswith("P1: found 1 A Street")
    plan = sent[-1][1]
    assert (plan["ended"], plan["order"], plan["reasons"]) == ("submitted", ["P1", "P2"], "P1 must be early")
    assert plan["home"] == {"address": "9 Home Street, Brooklyn 11209", "lon": -73.9, "lat": 40.9}
    assert plan["patients"][0] == {"id": "P1", "cells": [["name", "Ana"], ["address", "1 A St"], ["latest", "09:00"]],
                                   "place": {"address": "1 A Street, Brooklyn 11201", "lon": -73.1, "lat": 40.1}}
    schedule = plan["schedule"]
    # Five minutes between places, so the day is 08:00 to 09:15; P1's window is the one the model gave.
    assert (schedule["leave"], schedule["back"], schedule["working_minutes"], schedule["problems"]) == (
        "08:00", "09:15", 75, [])
    assert (schedule["travel_minutes"], schedule["between_minutes"], schedule["prefer"]) == (15, 5, "tightest group")
    assert schedule["stops"][0] == {"patient": "P1", "travel_minutes": 5, "arrive": "08:05", "wait_minutes": 0,
                                    "start": "08:05", "finish": "08:35", "earliest": None, "latest": "09:00",
                                    "late": False}
    assert plan["route"][0] == [[-73.9, 40.9], [-73.1, 40.1]]  # home to P1
    assert len(plan["route"]) == 3  # home, P1, P2, home


def test_a_plan_whose_places_were_not_all_found_has_no_schedule():
    look_up_one = {**LOOK_UP, "places": LOOK_UP["places"][:1]}
    app = create_app(scripted(look_up_one, SUBMIT), find, seconds, route)
    plan = events(post(app))[-1][1]
    assert (plan["order"], plan["schedule"], plan["route"], plan["home"]) == (["P1", "P2"], None, [], None)


def test_what_goes_wrong_is_sent_as_an_error():
    def ask(messages, schema, max_tokens):
        raise ConnectionError("the model isn't running")

    app = create_app(ask, find, seconds, route)
    assert events(post(app)) == [("error", {"message": "the model isn't running"})]
    assert events(post(app, csv="name,address\n")) == [
        ("error", {"message": "the patient list needs a header row and at least one patient"})]
    assert not app.state.busy.locked()  # freed for the next plan


def test_one_plan_at_a_time():
    app = create_app(scripted(), find, seconds, route)
    app.state.busy.acquire()
    response = post(app)
    assert response.status_code == 409
    assert "already" in response.json()["detail"]


def test_a_request_that_makes_no_sense_is_refused():
    app = create_app(scripted(), find, seconds, route)
    assert post(app, mode="flying").status_code == 422
    assert post(app, rules={"max_visits": "many"}).status_code == 422
    assert post(app, rules={"prefer": "the prettiest"}).status_code == 422


def test_the_sample_lists_come_with_a_home():
    samples = TestClient(create_app(scripted(), find, seconds, route)).get("/api/examples").json()
    names = [sample["name"] for sample in samples]
    assert "patients.csv" in names and "18th_avenue.csv" in names
    assert next(s for s in samples if s["name"] == "18th_avenue.csv")["home"] == "6302 18th Ave, Brooklyn"
    assert all(sample["csv"].startswith(("name,", "Patient,")) for sample in samples)


def test_the_page_is_served_once_built(tmp_path):
    (tmp_path / "index.html").write_text("<p>the page</p>")
    client = TestClient(create_app(scripted(), find, seconds, route, page=tmp_path))
    assert client.get("/").text == "<p>the page</p>"
    assert client.get("/api/examples").status_code == 200  # the API still comes first
    assert TestClient(create_app(scripted(), find, seconds, route, page=tmp_path / "none")).get("/").status_code == 404


def test_the_map_files_are_served_a_piece_at_a_time(tmp_path):
    (tmp_path / "nyc.pmtiles").write_bytes(bytes(range(100)))
    client = TestClient(create_app(scripted(), find, seconds, route, page=tmp_path / "none", map_data=tmp_path))
    piece = client.get("/map-data/nyc.pmtiles", headers={"Range": "bytes=10-19"})
    assert (piece.status_code, piece.content) == (206, bytes(range(10, 20)))


def test_by_subway_and_bus_each_leg_comes_with_its_segments():
    asked = []

    def itineraries(legs):
        asked.extend(legs)
        return [{"segments": [{"mode": "walk", "minutes": 5, "line": [[start.lon, start.lat], [end.lon, end.lat]]}],
                 "why": "the only way worth considering" if i == 0 else ""} for i, (start, end, _) in enumerate(legs)]

    app = create_app(scripted(LOOK_UP, BEST, SUBMIT), find, seconds, route, itineraries=itineraries)
    plan = events(post(app, mode="transit", rules={"max_visits": 2}))[-1][1]
    # Each leg sets off when the nurse leaves home (08:00), then when each visit finishes (08:35, 09:10).
    assert [when.strftime("%H:%M") for _, _, when in asked] == ["08:00", "08:35", "09:10"]
    assert len(plan["transit"]) == 3 and plan["transit"][0][0]["mode"] == "walk"
    assert plan["transit_why"] == ["the only way worth considering", "", ""]
    assert plan["route"][0] == [[-73.9, 40.9], [-73.1, 40.1]]  # the map's line: the segments' points, home to P1


def test_walking_and_driving_have_no_transit_segments():
    plan = events(post(create_app(scripted(LOOK_UP, BEST, SUBMIT), find, seconds, route), mode="walking"))[-1][1]
    assert plan["transit"] is None


def test_a_place_found_at_a_nearby_number_says_so_to_the_page():
    from homecare.web import shown_place
    assert shown_place(Place("715 58th Street", 40.6, -74.0, "717 isn't on 58th Street; ...")) == {
        "address": "715 58th Street", "lon": -74.0, "lat": 40.6, "note": "717 isn't on 58th Street; ..."}
    assert "note" not in shown_place(Place("715 58th Street", 40.6, -74.0))
