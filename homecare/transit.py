"""Travel times by subway and bus, walking to the stop, between stops and from the last one.

They come from R5, Conveyal's routing engine for public transport, run through r5py: R5 runs in
Java, inside this Python process. It starts only when the nurse travels this way, because starting
it takes a while: about 10 seconds for Java, then building the network of Brooklyn and Manhattan's
streets with the subway and bus timetables (data/osm, data/gtfs), about 75 seconds the first time;
the network is kept in data/r5 and read back after that.

A trip by subway and bus takes longer or shorter depending on when it starts: how long the wait for
the next train or bus is. The times here are typical ones: for each pair of places, the median over
departures through the nurse's working day, on the day planned for (weekday and weekend timetables
differ). R5 gives whole minutes. Ferries are never used: only the subway, buses, the Staten Island
Railway (in the subway timetable) and walking, which is also used on its own where it is quicker.

Everything R5 writes, its cache and temporary files, goes in data/r5, never on drive C.
"""

import csv
import datetime
import io
import math
import os
import pathlib
import shutil
import threading
import time
import zipfile

from homecare.addresses import Place

ROOT = pathlib.Path(__file__).resolve().parent.parent
JAVA = ROOT / "tools" / "jdk-21.0.13+9"
R5_JAR = ROOT / "tools" / "r5-v7.5.1-r5py-all.jar"
STREETS = ROOT / "data" / "osm" / "brooklyn-manhattan.osm.pbf"
TIMETABLES = ROOT / "data" / "gtfs"  # one GTFS zip per network: subway, Brooklyn buses, Manhattan buses, MTA Bus
WORK = ROOT / "data" / "r5"  # R5's settings, cache and temporary files
MAX_MEMORY = "8G"
# Walking speed, to and from stops and on its own: the road router's for walking (OSRM's foot profile),
# so that walking times are the same whichever way the nurse travels. R5's own is 3.6 km/h.
WALKING_KMH = 5.0

_lock = threading.Lock()
_r5py = None
_network = None


def _start():
    """Start Java and R5, once, with everything r5py writes kept in data/r5.

    r5py reads its settings from APPDATA/r5py.yml and keeps its cache in LOCALAPPDATA/r5py, both on
    drive C, and works them out as it is imported; so both point at data/r5 while it is imported."""
    global _r5py
    if _r5py is None:
        (WORK / "temp").mkdir(parents=True, exist_ok=True)
        clear_old_temporary_files()
        (WORK / "r5py.yml").write_text(f"r5-classpath: {R5_JAR.as_posix()}\nmax-memory: {MAX_MEMORY}\n"
                                       f"temporary-directory: {(WORK / 'temp').as_posix()}\n", encoding="utf-8")
        saved = {name: os.environ.get(name) for name in ("APPDATA", "LOCALAPPDATA")}
        os.environ["JAVA_HOME"] = str(JAVA)
        os.environ["APPDATA"] = os.environ["LOCALAPPDATA"] = str(WORK)
        try:
            import r5py
        finally:
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
        _r5py = r5py
    return _r5py


def clear_old_temporary_files(older_than: float = 3600) -> None:
    """Remove the temporary directories earlier runs left in data/r5/temp.

    r5py makes one each time it starts (copies of the map and timetables, about 17 MB once the
    network is cached) and leaves it; it can't be removed as the planner exits, since Java still has
    its files open then, on Windows. So each start removes those older than an hour."""
    for directory in (WORK / "temp").glob("r5py*"):
        if time.time() - directory.stat().st_mtime > older_than:
            shutil.rmtree(directory, ignore_errors=True)


def timetables() -> list[pathlib.Path]:
    return sorted(TIMETABLES.glob("*.zip"))


def service_dates(timetable: pathlib.Path) -> tuple[datetime.date, datetime.date]:
    """The first and last day a GTFS timetable runs on, from its calendar.txt."""
    with zipfile.ZipFile(timetable) as gtfs, gtfs.open("calendar.txt") as file:
        rows = list(csv.DictReader(io.TextIOWrapper(file, "utf-8-sig")))
    read = lambda text: datetime.datetime.strptime(text, "%Y%m%d").date()
    return min(read(row["start_date"]) for row in rows), max(read(row["end_date"]) for row in rows)


def check_dates(day: datetime.date, paths: list[pathlib.Path] | None = None) -> None:
    """Raise ValueError if a timetable doesn't run on `day`: there would be no trains or buses."""
    for timetable in timetables() if paths is None else paths:
        first, last = service_dates(timetable)
        if not first <= day <= last:
            raise ValueError(f"the timetable {timetable.name} runs from {first} to {last}, not on {day}; "
                             f"download a newer one into {TIMETABLES.relative_to(ROOT)}")


def network():
    """The transport network: streets, subway and buses. Built once, then read back from data/r5."""
    global _network
    with _lock:
        if _network is None:
            r5py = _start()
            _network = r5py.TransportNetwork(STREETS, timetables())
    return _network


def table(rows, size: int) -> list[list[int | None]]:
    """seconds[i][j] from R5's rows of (from_id, to_id, travel_time in minutes; NaN if there is no trip)."""
    seconds = [[None] * size for _ in range(size)]
    for start, end, minutes in rows:
        try:
            missing = minutes is None or math.isnan(float(minutes))
        except TypeError:  # pandas' NA
            missing = True
        seconds[int(start)][int(end)] = None if missing else int(minutes) * 60
    return seconds


def travel_seconds(places: list[Place], day: tuple[datetime.datetime, datetime.datetime]) -> list[list[int | None]]:
    """seconds[i][j]: typical seconds from places[i] to places[j] by subway, bus and walking, for
    departures from day[0] to day[1] (the median); None if there is no trip."""
    start, end = day
    check_dates(start.date())
    r5py = _start()
    import geopandas
    from shapely.geometry import Point

    points = geopandas.GeoDataFrame({"id": list(range(len(places)))},
                                    geometry=[Point(place.lon, place.lat) for place in places], crs="EPSG:4326")
    modes = [r5py.TransportMode.SUBWAY, r5py.TransportMode.BUS, r5py.TransportMode.RAIL, r5py.TransportMode.WALK]
    matrix = r5py.TravelTimeMatrix(network(), origins=points, destinations=points, departure=start,
                                   departure_time_window=max(end - start, datetime.timedelta(minutes=1)),
                                   transport_modes=modes, speed_walking=WALKING_KMH)
    return table(zip(matrix["from_id"], matrix["to_id"], matrix["travel_time"]), len(places))


# Routes along the streets and rails, for the map and the day's timeline: for each leg of the plan,
# a way to go at the time the nurse sets off, from the options R5 finds (DetailedItineraries). The
# quickest isn't always the one to take: a bus a minute slower can save a long walk with the
# equipment bag. So code keeps the options no other beats on both time and walking, and where more
# than one is left, the model judges how many extra minutes the walking saved is worth (judging.py).

_names = None


def names() -> tuple[dict, dict]:
    """Each stop's name, and each route's (short name, colour, text colour), from the timetables."""
    global _names
    if _names is None:
        stops, routes = {}, {}
        for timetable in timetables():
            with zipfile.ZipFile(timetable) as gtfs:
                with gtfs.open("stops.txt") as file:
                    for row in csv.DictReader(io.TextIOWrapper(file, "utf-8-sig")):
                        stops[row["stop_id"]] = row["stop_name"]
                with gtfs.open("routes.txt") as file:
                    for row in csv.DictReader(io.TextIOWrapper(file, "utf-8-sig")):
                        color, text = row.get("route_color", "").strip(), row.get("route_text_color", "").strip()
                        routes[row["route_id"]] = (row.get("route_short_name") or row["route_id"],
                                                   f"#{color}" if color else None, f"#{text}" if text else None)
        _names = stops, routes
    return _names


def quickest(segments: list[dict], start: datetime.datetime) -> list[dict]:
    """The option that arrives first, from R5's options for one trip.

    Each segment: option, segment (its place in the option), departure (a datetime, or None for
    walking all the way, which starts at `start`) and travel (a timedelta)."""
    options = {}
    for segment in segments:
        options.setdefault(segment["option"], []).append(segment)

    def arrival(option: list[dict]) -> datetime.datetime:
        now = start
        for segment in sorted(option, key=lambda s: s["segment"]):
            now = (segment["departure"] or now) + segment["travel"]
        return now

    best = min(options.values(), key=arrival)
    return sorted(best, key=lambda s: s["segment"])


def summaries(segments: list[dict], start: datetime.datetime) -> list[dict]:
    """Each option for one trip, with its segments in order, and added up: minutes from `start` to
    arriving, walking (km and minutes), and whether it rides a train or bus."""
    options = {}
    for segment in segments:
        options.setdefault(segment["option"], []).append(segment)
    out = []
    for option in options.values():
        option = sorted(option, key=lambda s: s["segment"])
        now = start
        for segment in option:
            now = (segment["departure"] or now) + segment["travel"]
        walks = [s for s in option if s["mode"] == "WALK"]
        out.append({"segments": option, "minutes": (now - start).total_seconds() / 60,
                    "walk_km": sum(s.get("distance", 0) for s in walks) / 1000,
                    "walk_minutes": sum(s["travel"].total_seconds() for s in walks) / 60,
                    "rides": len(walks) < len(option)})
    return out


def worth_considering(options: list[dict]) -> list[dict]:
    """The options no other beats: none is as quick and walks as little, and better at one of them.
    One of any two the same on both; the quickest first."""
    def beaten(o):
        return any(p["minutes"] <= o["minutes"] and p["walk_km"] <= o["walk_km"]
                   and (p["minutes"] < o["minutes"] or p["walk_km"] < o["walk_km"]) for p in options)
    kept = {}
    for o in sorted(options, key=lambda o: (o["minutes"], o["walk_km"])):
        if not beaten(o):
            kept.setdefault((round(o["minutes"]), round(o["walk_km"], 1)), o)
    return list(kept.values())


def choose(options: list[dict], worth) -> tuple[dict, str]:
    """The way to go, and why, if it isn't simply the only one worth considering.

    worth(quickest, fewer_km): how many extra minutes, at most, walking `fewer_km` less than the
    quickest option is worth to the nurse (the model's judgement). Of the slower options that walk
    less, those within what it's worth are fine; of those and the quickest, the least walking wins."""
    kept = worth_considering(options)
    quickest = kept[0]
    if len(kept) == 1:
        return quickest, ""
    best, why = quickest, ""
    for other in kept[1:]:
        extra, fewer = other["minutes"] - quickest["minutes"], quickest["walk_km"] - other["walk_km"]
        limit = worth(quickest, fewer)
        if limit is not None and extra <= limit and other["walk_km"] < best["walk_km"]:
            best = other
            why = (f"{round(extra)} min longer than the quickest way, {fewer:.1f} km less walking: "
                   f"worth up to {limit} min to the nurse")
    if best is quickest:
        why = "The ways with less walking take longer than it's worth to the nurse"
    return best, why


def shown(segments: list[dict]) -> list[dict]:
    """A trip's segments as the page shows them: how, for how long, on which route, between which stops."""
    stops, routes = names()
    out = []
    for s in segments:
        mode = s["mode"].lower()
        part = {"mode": mode, "minutes": max(round(s["travel"].total_seconds() / 60), 1 if mode != "walk" else 0),
                "line": s["line"]}
        if mode != "walk":
            route, color, text_color = routes.get(s["route"], (s["route"], None, None))
            part.update(route=route, color=color, text_color=text_color, depart=s["departure"].strftime("%H:%M"),
                        wait=round(s["wait"].total_seconds() / 60),
                        start=stops.get(s["start_stop"], s["start_stop"]), end=stops.get(s["end_stop"], s["end_stop"]))
        out.append(part)
    return out


def _rows(itineraries) -> list[dict]:
    """R5's GeoDataFrame of options as plain segments."""
    import pandas

    missing = lambda value: value is None or bool(pandas.isna(value))
    rows = []
    for row in itineraries.itertuples():
        mode = getattr(row.transport_mode, "name", str(row.transport_mode).split(".")[-1])
        rows.append({"option": row.option, "segment": row.segment, "mode": mode,
                     "departure": None if missing(row.departure_time) else row.departure_time.to_pydatetime(),
                     "travel": row.travel_time.to_pytimedelta(),
                     "wait": datetime.timedelta(0) if missing(row.wait_time) else row.wait_time.to_pytimedelta(),
                     "route": None if missing(row.route_id) else str(row.route_id),
                     "start_stop": None if missing(row.start_stop_id) else str(row.start_stop_id),
                     "end_stop": None if missing(row.end_stop_id) else str(row.end_stop_id),
                     "distance": 0.0 if missing(row.distance) else float(row.distance),  # metres
                     "line": points(row.geometry)})
    return rows


def points(geometry) -> list[list[float]]:
    """A segment's line as [longitude, latitude] points; a line in several parts is joined into one."""
    if geometry is None or geometry.is_empty:
        return []
    parts = getattr(geometry, "geoms", [geometry])  # a MultiLineString has parts; a LineString is one
    line = []
    for part in parts:
        for point in part.coords:
            point = [point[0], point[1]]
            if not line or point != line[-1]:
                line.append(point)
    return line


def itineraries(legs: list[tuple[Place, Place, datetime.datetime]], worth=None) -> list[dict]:
    """For each leg (from, to, when the nurse sets off), a way by subway, bus and walking: {"segments":
    segment by segment (see shown), "why": why this way, or ""}. With worth (see choose), the model
    weighs extra minutes against walking saved; without it, or if it fails, the quickest way."""
    r5py = _start()
    import geopandas
    from shapely.geometry import Point

    point = lambda place, id_: geopandas.GeoDataFrame({"id": [id_]}, geometry=[Point(place.lon, place.lat)],
                                                      crs="EPSG:4326")
    modes = [r5py.TransportMode.SUBWAY, r5py.TransportMode.BUS, r5py.TransportMode.RAIL, r5py.TransportMode.WALK]
    trips = []
    for start, end, when in legs:
        options = summaries(_rows(r5py.DetailedItineraries(network(), origins=point(start, 0),
                                                           destinations=point(end, 1), departure=when,
                                                           transport_modes=modes, speed_walking=WALKING_KMH)), when)
        try:
            way, why = choose(options, worth) if worth else (worth_considering(options)[0], "")
        except Exception:  # the model isn't there, or its answer can't be read: the quickest way
            way, why = worth_considering(options)[0], ""
        trips.append({"segments": shown(way["segments"]), "why": why})
    return trips
