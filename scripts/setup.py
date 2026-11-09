"""Download and build everything the planner needs that is not in the repository, into data/ and tools/.

Each step is skipped when what it makes is already there, so it can be run again after a failure, or
with --only to redo a step after deleting what it made. Before anything is downloaded, it lists the
steps to run and how much each downloads, and asks.

Run it from the project root, in the project's Python environment, with Docker running:
    python scripts/setup.py              # every step not done yet
    python scripts/setup.py --list       # what each step makes, and whether it is done
    python scripts/setup.py --only gtfs,map --yes
"""

import argparse
import concurrent.futures
import dataclasses
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
AGENT = "homecare-route-agent-setup"  # the name downloads go out under

OSM_URL = "https://download.geofabrik.de/north-america/us/new-york-latest.osm.pbf"
OSRM_IMAGE = "ghcr.io/project-osrm/osrm-backend:v5.27.1"  # as in compose.yaml
OSRM_PROFILES = {"walking": "foot", "driving": "car"}
GTFS_URL = "https://rrgtfsfeeds.s3.amazonaws.com/gtfs_{}.zip"
GTFS_FEEDS = ("subway", "b", "m", "busco")  # subway, Brooklyn buses, Manhattan buses, MTA Bus; no ferry
JAVA_URL = "https://api.adoptium.net/v3/binary/latest/21/ga/{os}/{arch}/jdk/hotspot/normal/eclipse"
PMTILES_VERSION = "1.31.2"
PMTILES_URL = "https://github.com/protomaps/go-pmtiles/releases/download/v{0}/{1}"
BUILDS_URL = "https://build-metadata.protomaps.dev/builds.json"
BUILD_URL = "https://build.protomaps.com/{}"
MAP_BOX = "-74.06,40.55,-73.83,40.89"  # Brooklyn and Manhattan, west, south, east, north
MAP_MAX_ZOOM = 15
ASSETS_URL = "https://raw.githubusercontent.com/protomaps/basemaps-assets/028c18f713baecad011301ff7a69acc39bcc2ae7/{}"
FONTS = ("Noto Sans Regular", "Noto Sans Medium", "Noto Sans Italic")
SPRITES = [f"{theme}{scale}.{kind}" for theme in ("light", "dark") for scale in ("", "@2x") for kind in ("json", "png")]


class SetupError(Exception):
    """A step cannot run, with what to do about it."""


@dataclasses.dataclass
class Step:
    name: str
    makes: str  # what it makes, for the list
    download: str  # how much it downloads, for the list
    done: Callable[[], bool]
    run: Callable[[], None]
    needs: tuple[str, ...] = ()  # steps whose results it uses


# Finding out what is there

def machine() -> tuple[str, str]:
    """This computer's system and processor: ("windows" | "linux" | "mac", "x64" | "arm64")."""
    system = {"Windows": "windows", "Linux": "linux", "Darwin": "mac"}.get(platform.system())
    arch = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine().lower())
    if system is None or arch is None:
        raise SetupError(f"no downloads for {platform.system()} on {platform.machine()}")
    return system, arch


def pmtiles_asset(system: str, arch: str) -> str:
    """The go-pmtiles release file for a computer (named a little differently for each system)."""
    cpu = {"x64": "x86_64", "arm64": "arm64"}[arch]
    return {"windows": f"go-pmtiles_{PMTILES_VERSION}_Windows_{cpu}.zip",
            "linux": f"go-pmtiles_{PMTILES_VERSION}_Linux_{cpu}.tar.gz",
            "mac": f"go-pmtiles-{PMTILES_VERSION}_Darwin_{cpu}.zip"}[system]


def font_files() -> list[str]:
    """Each font's files, in the basemap assets: one per range of 256 characters."""
    return [f"fonts/{font}/{start}-{start + 255}.pbf" for font in FONTS for start in range(0, 65536, 256)] + \
        ["fonts/OFL.txt"]


def latest_build(builds: list[dict]) -> str:
    """The newest daily world map in the Protomaps build list, e.g. "20261106.pmtiles"."""
    return max(build["key"] for build in builds if build["key"].endswith(".pmtiles"))


def osrm_done(folder: Path) -> bool:
    return (folder / "map.osrm.cell_metrics").exists()  # written by osrm-customize, the last of the three


def java_home(tools: Path) -> Path | None:
    """The Java in tools/ (a folder jdk-*), as homecare/transit.py finds it."""
    javas = sorted(path for path in tools.glob("jdk-*") if path.is_dir())
    return javas[-1] if javas else None


# Downloading

def request(url: str, method: str = "GET") -> urllib.request.Request:
    return urllib.request.Request(url, method=method, headers={"User-Agent": AGENT})


def size(url: str) -> int | None:
    """How many bytes a download is, if the server says."""
    try:
        with urllib.request.urlopen(request(url, "HEAD"), timeout=30) as response:
            length = response.headers.get("Content-Length")
            return int(length) if length else None
    except OSError:
        return None


def download(url: str, path: Path, quiet: bool = False) -> None:
    """Download to path, a piece at a time; into path.part first, so that a download cut short is never
    taken for a whole one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    with urllib.request.urlopen(request(url), timeout=60) as response, open(part, "wb") as file:
        total, got, shown = int(response.headers.get("Content-Length") or 0), 0, -1
        while chunk := response.read(1 << 20):
            file.write(chunk)
            got += len(chunk)
            if not quiet and total and got * 20 // total != shown:  # every 5%
                shown = got * 20 // total
                print(f"\r  {path.name}: {got >> 20} of {total >> 20} MB", end="", flush=True)
    if not quiet and total:
        print()
    part.replace(path)


def unpack(archive: Path, into: Path) -> Path:
    """Unpack an archive into a new folder of its own; that folder."""
    into.mkdir(parents=True)
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as files:
            files.extractall(into)
    else:
        with tarfile.open(archive) as files:
            files.extractall(into, filter="data")  # nothing outside the folder, no links out of it
    return into


def run(command: list[str]) -> None:
    print("  " + " ".join(command), flush=True)
    if subprocess.run(command).returncode != 0:
        raise SetupError(f"{' '.join(command[:2])} failed, as shown above")


# The steps

def steps(root: Path = ROOT) -> list[Step]:
    data, tools = root / "data", root / "tools"
    osm = data / "osm" / "new-york-latest.osm.pbf"
    index = data / "addresses.db"
    streets = data / "osm" / "brooklyn-manhattan.osm.pbf"
    osrm = data / "osrm"
    gtfs = data / "gtfs"
    map_data = data / "map"

    def get_osm():
        download(OSM_URL, osm)

    def build_addresses():
        import build_addresses  # the scripts beside this one; they need osmium
        part = index.with_name("addresses.part.db")
        print(f"  {build_addresses.build(osm, part)} addresses")
        part.replace(index)

    def extract_streets():
        import extract_streets
        part = streets.with_name("brooklyn-manhattan.part.osm.pbf")  # osmium writes by the file's ending
        extract_streets.extract(osm, part)
        part.replace(streets)

    def build_osrm():
        if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
            raise SetupError("Docker is not running: start it, then run this again")
        for mode, profile in OSRM_PROFILES.items():
            folder = osrm / mode
            if osrm_done(folder):
                continue
            folder.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(osm, folder / "map.osm.pbf")
            volume = ["docker", "run", "--rm", "-v", f"{folder.resolve()}:/data", OSRM_IMAGE]
            run(volume + ["osrm-extract", "-p", f"/opt/{profile}.lua", "/data/map.osm.pbf"])
            run(volume + ["osrm-partition", "/data/map.osrm"])
            run(volume + ["osrm-customize", "/data/map.osrm"])
            (folder / "map.osm.pbf").unlink()

    def get_gtfs():
        for feed in GTFS_FEEDS:
            if not (gtfs / f"gtfs_{feed}.zip").exists():
                download(GTFS_URL.format(feed), gtfs / f"gtfs_{feed}.zip")

    def get_java():
        system, arch = machine()
        url = JAVA_URL.format(os=system, arch={"x64": "x64", "arm64": "aarch64"}[arch])
        work = tools / ".download"
        shutil.rmtree(work, ignore_errors=True)
        archive = work / ("java.zip" if system == "windows" else "java.tar.gz")
        download(url, archive)
        folder = next(unpack(archive, work / "unpacked").glob("jdk-*"))
        home = folder / "Contents" / "Home" if system == "mac" else folder  # a Mac's Java is inside a bundle
        home.replace(tools / folder.name)
        shutil.rmtree(work)

    def make_map():
        pmtiles = tools / "pmtiles" / ("pmtiles.exe" if sys.platform == "win32" else "pmtiles")
        if not pmtiles.exists():
            asset = pmtiles_asset(*machine())
            work = tools / ".download"
            shutil.rmtree(work, ignore_errors=True)
            download(PMTILES_URL.format(PMTILES_VERSION, asset), work / asset)
            unpack(work / asset, work / "unpacked").replace(tools / "pmtiles")
            pmtiles.chmod(0o755)  # a zip keeps no file modes
            shutil.rmtree(work)
        tiles = map_data / "nyc.pmtiles"
        if not tiles.exists():
            with urllib.request.urlopen(request(BUILDS_URL), timeout=30) as response:
                build = latest_build(json.load(response))
            map_data.mkdir(parents=True, exist_ok=True)
            part = map_data / "nyc.part.pmtiles"
            run([str(pmtiles), "extract", BUILD_URL.format(build), str(part), f"--bbox={MAP_BOX}",
                 f"--maxzoom={MAP_MAX_ZOOM}"])
            part.replace(tiles)
        assets = [(name, map_data / name) for name in font_files()] + \
                 [(f"sprites/v4/{name}", map_data / "sprites" / "v4" / name) for name in SPRITES]
        missing = [(name, path) for name, path in assets if not path.exists()]
        if missing:
            print(f"  {len(missing)} font and icon files", flush=True)
            with concurrent.futures.ThreadPoolExecutor(8) as pool:
                for future in [pool.submit(download, ASSETS_URL.format(urllib.parse.quote(name)), path, True)
                               for name, path in missing]:
                    future.result()

    def map_done():
        return (map_data / "nyc.pmtiles").exists() and all((map_data / name).exists() for name in font_files()) \
            and all((map_data / "sprites" / "v4" / name).exists() for name in SPRITES)

    return [
        Step("osm", "data/osm/new-york-latest.osm.pbf: OpenStreetMap, New York state", "about 500 MB",
             osm.exists, get_osm),
        Step("addresses", "data/addresses.db: the address index (about 3 minutes)", "nothing",
             index.exists, build_addresses, ("osm",)),
        Step("streets", "data/osm/brooklyn-manhattan.osm.pbf: streets for the subway and bus (about 3 minutes)",
             "nothing", streets.exists, extract_streets, ("osm",)),
        Step("osrm", "data/osrm/walking, data/osrm/driving: road networks, 4.6 GB (in Docker; the longest step)",
             "the OSRM image, if Docker does not have it",
             lambda: all(osrm_done(osrm / mode) for mode in OSRM_PROFILES), build_osrm, ("osm",)),
        Step("gtfs", "data/gtfs: the MTA's subway and bus timetables", "about 40 MB",
             lambda: all((gtfs / f"gtfs_{feed}.zip").exists() for feed in GTFS_FEEDS), get_gtfs),
        Step("java", "tools/jdk-*: Java 21 (Temurin), for the subway and bus; skipped if JAVA_HOME is set",
             "about 200 MB", lambda: java_home(tools) is not None or bool(os.environ.get("JAVA_HOME")), get_java),
        Step("map", "data/map: the offline map for the page, and tools/pmtiles to cut it", "about 70 MB",
             map_done, make_map),
    ]


def choose(all_steps: list[Step], only: str | None) -> list[Step]:
    """The steps to run: those named (each, done or not), or else every one not done. A step whose
    needs are not done, and not among them, cannot run."""
    by_name = {step.name: step for step in all_steps}
    if only:
        names = [name.strip() for name in only.split(",") if name.strip()]
        unknown = [name for name in names if name not in by_name]
        if unknown:
            raise SetupError(f"no step {', '.join(unknown)}; the steps are {', '.join(by_name)}")
        chosen = [step for step in all_steps if step.name in names]
    else:
        chosen = [step for step in all_steps if not step.done()]
    for step in chosen:
        for need in step.needs:
            if not by_name[need].done() and by_name[need] not in chosen:
                raise SetupError(f"step {step.name} needs step {need} first")
    return chosen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", help="the steps to run, done or not, e.g. gtfs,map")
    parser.add_argument("--list", action="store_true", help="list the steps, and whether each is done")
    parser.add_argument("--yes", action="store_true", help="do not ask before starting")
    args = parser.parse_args()
    all_steps = steps()
    if args.list:
        for step in all_steps:
            print(f"{'done' if step.done() else '    '}  {step.name:<10} {step.makes}")
        return
    try:
        chosen = choose(all_steps, args.only)
        if not chosen:
            print("Everything is there already.")
        else:
            print("To run:")
            for step in chosen:
                print(f"  {step.name:<10} {step.makes}; downloads {step.download}")
            if any(step.name == "osm" for step in chosen):
                known = size(OSM_URL)
                if known:
                    print(f"  (the OpenStreetMap file is {known >> 20} MB today)")
            if not args.yes:
                try:
                    if input("Go ahead? [y/N] ").strip().lower() not in ("y", "yes"):
                        return
                except EOFError:
                    return
            for step in chosen:
                print(f"== {step.name}", flush=True)
                step.run()
        print("Next: docker compose up -d (the road routers), then the commands in the README.")
    except SetupError as error:
        sys.exit(f"setup: {error}")


if __name__ == "__main__":
    main()
