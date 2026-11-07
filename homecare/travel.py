"""Travel times between places, from the road routers (OSRM) running locally in Docker.

Start them with `docker compose up -d`. There is one router per way of travelling, each with the
road network built for it in data/osrm. One request to a router's table service gives the travel
time from every place to every other place.
"""

import json
import urllib.error
import urllib.request

from homecare.addresses import Place

# Each way of travelling: its router, and OSRM's name for it in the request.
MODES = {
    "walking": ("http://localhost:5001", "foot"),
    "driving": ("http://localhost:5000", "car"),
}


def ask_router(service: str, places: list[Place], mode: str, options: str) -> dict:
    """Ask the router for `mode` its `service` (table, route) over `places`; its reply, if Ok."""
    if mode not in MODES:
        raise ValueError(f'no way of travelling called "{mode}"; there are {", ".join(MODES)}')
    server, profile = MODES[mode]
    coordinates = ";".join(f"{place.lon},{place.lat}" for place in places)  # OSRM wants longitude first
    url = f"{server}/{service}/v1/{profile}/{coordinates}?{options}"
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            reply = json.load(response)
    except urllib.error.HTTPError as refused:  # OSRM answers a bad request with an error code and the reason
        reply = json.load(refused)
    except OSError as problem:
        raise ConnectionError(f"the {mode} road router at {server} didn't answer; is it running "
                              f"(docker compose up -d)? {problem}") from problem
    if reply.get("code") != "Ok":
        raise ValueError(f"the road router refused the request: {reply.get('message', reply.get('code'))}")
    return reply


def travel_minutes(places: list[Place], mode: str = "walking") -> list[list[int | None]]:
    """minutes[i][j]: minutes from places[i] to places[j] by `mode`, rounded; None if there is no route.

    Driving times are OSRM's: no traffic, and no time to park."""
    reply = ask_router("table", places, mode, "annotations=duration")
    return [[None if seconds is None else round(seconds / 60) for seconds in row] for row in reply["durations"]]


def route(places: list[Place], mode: str = "walking") -> list[list[list[float]]]:
    """The way along the streets from each place to the next, in order: one line per leg, each a list
    of [longitude, latitude] points (GeoJSON's order, as maps draw it)."""
    reply = ask_router("route", places, mode, "overview=false&steps=true&geometries=geojson")
    lines = []
    for leg in reply["routes"][0]["legs"]:
        line = []
        for step in leg["steps"]:
            for point in step["geometry"]["coordinates"]:
                if not line or point != line[-1]:  # each step starts where the one before ended
                    line.append(point)
        lines.append(line)
    return lines
