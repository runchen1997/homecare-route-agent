"""Travel times between places, from the road router (OSRM) running locally in Docker.

Start it with `docker compose up -d`. One request to OSRM's table service gives the travel time
from every place to every other place, along the walking road network in data/osrm/walking.
"""

import json
import urllib.error
import urllib.request

from homecare.addresses import Place

WALKING = "http://localhost:5001"


def walking_minutes(places: list[Place], server: str = WALKING) -> list[list[int | None]]:
    """minutes[i][j]: walking minutes from places[i] to places[j], rounded; None if there is no route."""
    coordinates = ";".join(f"{place.lon},{place.lat}" for place in places)  # OSRM wants longitude first
    url = f"{server}/table/v1/foot/{coordinates}?annotations=duration"
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            reply = json.load(response)
    except urllib.error.HTTPError as refused:  # OSRM answers a bad request with an error code and the reason
        reply = json.load(refused)
    except OSError as problem:
        raise ConnectionError(f"the road router at {server} didn't answer; is it running "
                              f"(docker compose up -d)? {problem}") from problem
    if reply.get("code") != "Ok":
        raise ValueError(f"the road router refused the request: {reply.get('message', reply.get('code'))}")
    return [[None if seconds is None else round(seconds / 60) for seconds in row] for row in reply["durations"]]
