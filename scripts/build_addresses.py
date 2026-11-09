"""Build the offline address index (data/addresses.db) from an OpenStreetMap extract of New York.

The index has one row per address in Brooklyn and Manhattan: every node or building in the map with
a house number and a street, its borough from its zip code, and its place on the map (a building's
is the average of its outline's points; an address in the map more than once, the average of its
places). Streets are written as homecare/addresses.py looks them up: lower case, words in full.

Run it from the project root; for New York state it takes about 3 minutes:
    python scripts/build_addresses.py data/osm/new-york-latest.osm.pbf data/addresses.db
"""

import argparse
import collections
import pathlib
import re
import sqlite3
import sys

import osmium

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))  # to run from the project root
from homecare.addresses import DIRECTIONS, STREET_TYPES

# Around the two boroughs. Some addresses in the map have a wrong zip code: "Sarles Lane", 50 km north, has one
# in Brooklyn.
BOX = (-74.06, 40.55, -73.83, 40.89)  # west, south, east, north


def borough_of(zip_code: str) -> str | None:
    """The borough a zip code is in, of the two the index covers; None for any other."""
    if zip_code.startswith("112"):
        return "Brooklyn"
    if zip_code[:3] in ("100", "101", "102"):
        return "Manhattan"
    return None


def street_key(street: str) -> str:
    """A street as the index looks it up: "W. 85th St" is "west 85th street", "Saint John's Pl" "saint johns place"."""
    words = street.lower().replace(".", "").replace("'", "").replace("\u2019", "").split()
    if not words:
        return ""
    words[-1] = STREET_TYPES.get(words[-1], words[-1])
    if len(words) > 1:
        words[0] = DIRECTIONS.get(words[0], words[0])
    return " ".join(words)


def house_value(number: str) -> int | None:
    """A house number's value, for finding those near it: 85 for "85b"; none for a range, "144-176"."""
    match = re.fullmatch(r"(\d+)[a-z]*", number)
    return int(match[1]) if match else None


def rows(addresses: list[tuple]) -> list[tuple]:
    """The index's rows, from each address as the map has it: (number, street, zip code, lat, lon).
    Only those in Brooklyn or Manhattan, and each once, at the average of its places."""
    west, south, east, north = BOX
    found = collections.defaultdict(list)
    for number, street, zip_code, lat, lon in addresses:
        number, zip_code = number.strip().lower(), zip_code.strip()[:5]
        key, borough = street_key(street), borough_of(zip_code)
        if number and key and borough and west <= lon <= east and south <= lat <= north:
            found[number, key, borough].append((street.strip(), zip_code, lat, lon))
    out = []
    for (number, key, borough), places in found.items():
        street, zip_code = places[0][:2]
        out.append((number, house_value(number), key, street, borough, zip_code,
                    sum(p[2] for p in places) / len(places), sum(p[3] for p in places) / len(places)))
    return out


class Addresses(osmium.SimpleHandler):
    """Collects the addresses in the map: nodes, and ways such as a building's outline."""

    def __init__(self):
        super().__init__()
        self.found = []

    def add(self, tags, lat: float, lon: float) -> None:
        self.found.append((tags.get("addr:housenumber", ""), tags.get("addr:street", ""),
                           tags.get("addr:postcode", ""), lat, lon))

    def node(self, n) -> None:
        if "addr:housenumber" in n.tags:
            self.add(n.tags, n.location.lat, n.location.lon)

    def way(self, w) -> None:
        if "addr:housenumber" in w.tags:
            points = [(node.location.lat, node.location.lon) for node in w.nodes if node.location.valid()]
            if points:
                self.add(w.tags, sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))


def build(osm: pathlib.Path, index: pathlib.Path) -> int:
    """Write the index from the map; how many addresses it has."""
    addresses = Addresses()
    addresses.apply_file(str(osm), locations=True)  # locations: a way's nodes come with their places
    index.unlink(missing_ok=True)
    db = sqlite3.connect(index)
    db.execute("CREATE TABLE addresses (number TEXT, number_value INTEGER, street TEXT, display TEXT, "
               "borough TEXT, zip TEXT, lat REAL, lon REAL)")
    index_rows = rows(addresses.found)
    db.executemany("INSERT INTO addresses VALUES (?, ?, ?, ?, ?, ?, ?, ?)", index_rows)
    db.execute("CREATE INDEX by_street ON addresses (street, borough)")
    db.commit()
    db.close()
    return len(index_rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("osm", type=pathlib.Path, help="an OpenStreetMap extract (.osm.pbf) that covers both boroughs")
    parser.add_argument("index", type=pathlib.Path, help="the index to write; replaced if it exists")
    args = parser.parse_args()
    print(f"{build(args.osm, args.index)} addresses written to {args.index}")


if __name__ == "__main__":
    main()
