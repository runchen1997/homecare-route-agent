"""The planner as a local web service, for the nurse's page.

It listens on 127.0.0.1 only, so nothing outside this computer can reach it, and patient
addresses stay here. POST /api/plan starts the agent and answers with a stream of Server-Sent
Events, so the page shows each step as the model takes it (a plan takes 20-35 seconds):

    event: step   each step: its number, the model's thinking, the action, its arguments, the result
    event: plan   once the model is done: the schedule, the places, the route along the streets
    event: error  what went wrong, e.g. the model or a road router isn't running

One plan at a time: the model runs on the one graphics card.

Run it (Ollama and the road routers must be running):
    python -m homecare.web
"""

import dataclasses
import json
import pathlib
import queue
import threading
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from homecare import addresses, agent, checking, llm, travel

HOST, PORT = "127.0.0.1", 8000
ROOT = pathlib.Path(__file__).resolve().parent.parent
PAGE = ROOT / "frontend" / "dist"  # the page, once built (cd frontend; npm run build)
# The offline map: the streets of Brooklyn and Manhattan (nyc.pmtiles), and the fonts and icons it is drawn with.
MAP_DATA = ROOT / "data" / "map"
EXAMPLES = ROOT / "examples"
# A home for each sample list, the one its patients were made up around.
EXAMPLE_HOMES = {"18th_avenue.csv": "6302 18th Ave, Brooklyn"}
DEFAULT_HOME = "1025 70th St, Brooklyn"


class PlanRequest(BaseModel):
    csv: str  # the patient list, as the nurse wrote it
    home: str
    mode: Literal[tuple(travel.MODES)] = "walking"
    rules: checking.Rules = Field(default_factory=checking.Rules)  # any rule left out keeps its default


def shown_place(place: addresses.Place | None) -> dict | None:
    return None if place is None else {"address": place.display, "lon": place.lon, "lat": place.lat}


def shown_plan(planner: agent.Agent, result: agent.Result, seconds, route) -> dict:
    """What the page shows once the model is done: every patient, and the plan the model submitted,
    checked against the windows it gave, with the route along the streets.

    seconds(places) and route(places) are travel times and the route's lines, the way the nurse travels."""
    found = planner.found
    plan = {
        "ended": result.ended,
        "order": result.order,
        "reasons": result.reasons,
        "home": shown_place(found.get("home")),
        "patients": [{"id": patient_id, "cells": row, "place": shown_place(found.get(patient_id))}
                     for patient_id, row in zip(planner.ids, agent.cells(planner.request.csv_text))],
        "schedule": None,
        "route": [],
    }
    stops = ["home", *result.order, "home"]
    if not result.order or any(place not in found for place in stops):
        return plan
    places = [found[place] for place in stops]
    table = seconds(places)
    legs = [table[i][i + 1] for i in range(len(places) - 1)]
    check = checking.check(result.order, planner.windows, legs, planner.request.rules)
    clock, shown = checking.clock, checking.shown  # times are worked out in seconds, shown in minutes
    plan["schedule"] = {
        "leave": clock(check.leave), "back": clock(check.back), "working_minutes": shown(check.back - check.leave),
        "travel_minutes": shown(check.travel), "between_minutes": shown(check.between_patients),
        "waiting_minutes": shown(check.waiting), "prefer": planner.request.rules.prefer,
        "travel_home_minutes": shown(legs[-1]), "problems": check.problems,
        "stops": [{"patient": stop.patient, "travel_minutes": shown(stop.travel), "arrive": clock(stop.arrive),
                   "wait_minutes": shown(stop.wait), "start": clock(stop.start), "finish": clock(stop.finish),
                   "earliest": None if stop.earliest is None else clock(stop.earliest),
                   "latest": None if stop.latest is None else clock(stop.latest), "late": stop.late}
                  for stop in check.stops],
    }
    plan["route"] = route(places)
    return plan


def create_app(ask=llm.ask, find=addresses.find, seconds=travel.travel_seconds, route=travel.route,
               page: pathlib.Path = PAGE, map_data: pathlib.Path = MAP_DATA) -> FastAPI:
    """The web service. The model, the address index and the road routers can be swapped for stand-ins.

    seconds(places, mode) and route(places, mode) are as in homecare.travel. The page is served
    from `page` if it has been built, and the map's files from `map_data` if they are there."""
    app = FastAPI(title="Home-care route planner")
    app.state.busy = threading.Lock()  # held while a plan is being worked out

    @app.get("/api/examples")
    def examples() -> list[dict]:
        """The sample patient lists (made up), each with a home to plan from."""
        return [{"name": path.name, "csv": path.read_text(encoding="utf-8"),
                 "home": EXAMPLE_HOMES.get(path.name, DEFAULT_HOME)}
                for path in sorted(EXAMPLES.glob("*.csv"))]

    @app.post("/api/plan")
    def plan(request: PlanRequest) -> StreamingResponse:
        if not app.state.busy.acquire(blocking=False):
            raise HTTPException(409, "A plan is being worked out already; wait for it to finish.")
        events = queue.Queue()  # (event name, data); None once the run is over

        def work() -> None:
            try:
                by_mode = lambda places: seconds(places, request.mode)
                planner = agent.Agent(
                    agent.Request(request.csv, request.home, request.rules, request.mode), ask,
                    log=lambda *_: None, find=find, seconds=by_mode,
                    on_step=lambda number, step: events.put(("step", {"number": number, **dataclasses.asdict(step)})))
                result = planner.run()
                events.put(("plan", shown_plan(planner, result, by_mode, lambda places: route(places, request.mode))))
            except Exception as problem:  # anything at all: the page must hear of it, not wait forever
                events.put(("error", {"message": str(problem)}))
            finally:
                events.put(None)
                app.state.busy.release()

        # The agent runs in its own thread; this stream passes on what it puts in the queue. If the page
        # goes away, the run still finishes (one model call can't be stopped halfway), then frees the planner.
        threading.Thread(target=work, daemon=True).start()

        def stream():
            while (event := events.get()) is not None:
                name, data = event
                yield f"event: {name}\ndata: {json.dumps(data)}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    if map_data.is_dir():  # the map reads nyc.pmtiles a piece at a time, with HTTP range requests
        app.mount("/map-data", StaticFiles(directory=map_data), name="map-data")
    if page.is_dir():  # last, so /api/... and /map-data/... are never taken for a file of the page
        app.mount("/", StaticFiles(directory=page, html=True), name="page")
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
