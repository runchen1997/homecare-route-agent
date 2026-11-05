"""Find where an address is, in the offline address index (data/addresses.db).

The index has one row per address in Brooklyn and Manhattan: house number, street (lower case,
words in full, e.g. "east 14th street"), borough, zip, latitude and longitude. An address is
found only if its house number and street match a row exactly; this module never guesses.
"""

import contextlib
import dataclasses
import pathlib
import re
import sqlite3

INDEX = pathlib.Path(__file__).resolve().parent.parent / "data" / "addresses.db"
BOROUGHS = {"brooklyn": "Brooklyn", "manhattan": "Manhattan"}
# Short forms nurses write, and the full words the index uses.
STREET_TYPES = {"ave": "avenue", "av": "avenue", "st": "street", "pkwy": "parkway", "blvd": "boulevard",
                "pl": "place", "rd": "road", "dr": "drive", "ln": "lane", "ct": "court", "ter": "terrace"}
DIRECTIONS = {"e": "east", "w": "west", "n": "north", "s": "south"}


@dataclasses.dataclass
class Place:
    display: str  # the address as the index writes it, e.g. "6502 18th Avenue, Brooklyn 11204"
    lat: float
    lon: float


class AddressError(ValueError):
    """The address wasn't found, or matches more than one place. The message says which, and why."""


def parse(text: str) -> tuple[str, str, str | None]:
    """The house number, street (in the index's words) and borough (or None) in `text`."""
    parts = [" ".join(part.split()) for part in text.lower().replace(".", "").split(",")]
    match = re.fullmatch(r"(\d+(?:-\d+)?) (.+)", parts[0])
    if not match:
        raise AddressError(f'not found: could not read "{text}"; write it as number, street, borough, '
                           f'e.g. "6302 18th Ave, Brooklyn"')
    number, words = match[1], match[2].split()
    words[-1] = STREET_TYPES.get(words[-1], words[-1])
    if len(words) > 1:
        words[0] = DIRECTIONS.get(words[0], words[0])
    # The borough is any later part that starts with one, e.g. "Brooklyn" or "Brooklyn NY 11204".
    borough = next((BOROUGHS[part.split()[0]] for part in parts[1:] if part and part.split()[0] in BOROUGHS), None)
    return number, " ".join(words), borough


def find(text: str, index: pathlib.Path = INDEX) -> Place:
    """Where the address `text` is. Raises AddressError if it isn't found, or is in two boroughs."""
    number, street, borough = parse(text)
    where = " in " + borough if borough else ""
    if not index.exists():
        raise FileNotFoundError(f"the address index {index} is missing")
    # Read-only, so a wrong path fails instead of making an empty index; closing() closes it after.
    with contextlib.closing(sqlite3.connect(index.as_uri() + "?mode=ro", uri=True)) as db:
        on_street = "street = ? AND (? IS NULL OR borough = ?)"
        street_name = db.execute(f"SELECT display FROM addresses WHERE {on_street} LIMIT 1",
                                 (street, borough, borough)).fetchone()
        if street_name is None:
            raise AddressError(f'not found: no street called "{street}"{where} in the address index')
        rows = db.execute(f"SELECT display, borough, zip, lat, lon FROM addresses WHERE {on_street} AND number = ?",
                          (street, borough, borough, number)).fetchall()
    if not rows:
        raise AddressError(f"not found: {street_name[0]}{where} has no number {number}")
    if len({row[1] for row in rows}) > 1:
        raise AddressError(f"unclear: {number} {rows[0][0]} is in both Brooklyn and Manhattan; add the borough")
    display, borough, zip_code, lat, lon = rows[0]
    return Place(f"{number} {display}, {borough} {zip_code}", lat, lon)
