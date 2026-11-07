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
import threading
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
