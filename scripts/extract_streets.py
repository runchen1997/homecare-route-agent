"""Cut the streets of Brooklyn and Manhattan out of an OpenStreetMap extract of New York, for R5.

R5 (homecare/transit.py) builds its network from a map and the timetables, and needs only the
streets, in the area the nurse travels: all of New York state would take far more time and memory.
This keeps every way tagged highway with a point in the box, the nodes they use, and the turn
restrictions among them.

Run it from the project root; it reads the whole extract twice, a few minutes:
    python scripts/extract_streets.py data/osm/new-york-latest.osm.pbf data/osm/brooklyn-manhattan.osm.pbf
"""

import argparse
import pathlib

import osmium

BOX = (-74.06, 40.56, -73.78, 40.90)  # west, south, east, north


def inside(location) -> bool:
    west, south, east, north = BOX
    return location.valid() and west <= location.lon <= east and south <= location.lat <= north


class Choose(osmium.SimpleHandler):
    """The first read: which ways, nodes and turn restrictions to keep."""

    def __init__(self):
        super().__init__()
        self.ways, self.nodes, self.relations = set(), set(), set()

    def way(self, w) -> None:
        if "highway" in w.tags and any(inside(node.location) for node in w.nodes):
            self.ways.add(w.id)
            self.nodes.update(node.ref for node in w.nodes)

    def relation(self, r) -> None:
        if r.tags.get("type") == "restriction":
            ways = [member.ref for member in r.members if member.type == "w"]
            if ways and all(way in self.ways for way in ways):
                self.relations.add(r.id)


class Keep(osmium.SimpleHandler):
    """The second read: write what was chosen."""

    def __init__(self, chosen: Choose, writer):
        super().__init__()
        self.chosen, self.writer = chosen, writer

    def node(self, n) -> None:
        if n.id in self.chosen.nodes:
            self.writer.add_node(n)

    def way(self, w) -> None:
        if w.id in self.chosen.ways:
            self.writer.add_way(w)

    def relation(self, r) -> None:
        if r.id in self.chosen.relations:
            self.writer.add_relation(r)


def extract(source: pathlib.Path, streets: pathlib.Path) -> Choose:
    chosen = Choose()
    chosen.apply_file(str(source), locations=True)  # locations: a way's nodes come with their places
    streets.unlink(missing_ok=True)
    writer = osmium.SimpleWriter(str(streets))
    try:
        Keep(chosen, writer).apply_file(str(source))
    finally:
        writer.close()
    return chosen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", type=pathlib.Path, help="an OpenStreetMap extract (.osm.pbf) that covers the box")
    parser.add_argument("streets", type=pathlib.Path, help="the file to write; replaced if it exists")
    args = parser.parse_args()
    chosen = extract(args.source, args.streets)
    print(f"{len(chosen.nodes)} nodes, {len(chosen.ways)} ways, {len(chosen.relations)} restrictions "
          f"written to {args.streets}")


if __name__ == "__main__":
    main()
