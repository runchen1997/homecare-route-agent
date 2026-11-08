"""Find where an address is, in the offline address index (data/addresses.db).

The index has one row per address in Brooklyn and Manhattan: house number, street (lower case,
words in full, e.g. "east 14th street"), borough, zip, latitude and longitude. An address is
found only if its street matches a row exactly, and its house number too, but for one: a house
number the street doesn't have, with one nearby on the same side, is taken to be that one (the
nearest; the lower of two as near), and the place found says so, for the nurse to check.
"""

import contextlib
import dataclasses
import pathlib
import re
import sqlite3

INDEX = pathlib.Path(__file__).resolve().parent.parent / "data" / "addresses.db"
# Each borough, as nurses write it: in full, or as New Yorkers shorten it.
BOROUGHS = {"brooklyn": "Brooklyn", "bk": "Brooklyn", "bklyn": "Brooklyn", "manhattan": "Manhattan"}
# Short forms nurses write, and the full words the index uses.
STREET_TYPES = {"ave": "avenue", "av": "avenue", "st": "street", "pkwy": "parkway", "blvd": "boulevard",
                "pl": "place", "rd": "road", "dr": "drive", "ln": "lane", "ct": "court", "ter": "terrace"}
DIRECTIONS = {"e": "east", "w": "west", "n": "north", "s": "south"}
NEARBY = 50  # how far, in house numbers, a number the street has is "nearby"


@dataclasses.dataclass
class Place:
    display: str  # the address as the index writes it, e.g. "6502 18th Avenue, Brooklyn 11204"
    lat: float
    lon: float
    note: str = ""  # how it differs from the address asked for, if it does


# How to write an address, for the model. The example has no real street in it: with one, the
# model copied it ("1025 18th Avenue" for a home on 70th St), which could find the wrong place.
HOW_TO_WRITE = ('write it as house number, street name with its type (St, Ave, Pkwy, ...), borough, '
                'e.g. "<number> <name> St, Brooklyn"')


class AddressError(ValueError):
    """The address wasn't found, or matches more than one place. The message says which, and why."""


def parse(text: str) -> tuple[str, str, str | None]:
    """The house number, street (in the index's words) and borough (or None) in `text`."""
    parts = [" ".join(part.split()) for part in text.lower().replace(".", "").split(",")]
    match = re.fullmatch(r"(\d+(?:-\d+)?) (.+)", parts[0])
    if not match:
        raise AddressError(f'not found: could not read "{text}"; {HOW_TO_WRITE}')
    number, words = match[1], match[2].split()
    # A borough written after the street without a comma: "618 58th st bk".
    borough = BOROUGHS[words.pop()] if len(words) > 2 and words[-1] in BOROUGHS else None
    words = [ordinal(word) for word in words]
    words[-1] = STREET_TYPES.get(words[-1], words[-1])
    if len(words) > 1:
        words[0] = DIRECTIONS.get(words[0], words[0])
    # The borough is any later part that starts with one, e.g. "Brooklyn" or "Brooklyn NY 11204".
    borough = borough or next((BOROUGHS[part.split()[0]] for part in parts[1:]
                               if part and part.split()[0] in BOROUGHS), None)
    return number, " ".join(words), borough


def ordinal(word: str) -> str:
    """A numbered street's name with the right ending: "53th" is 53rd, "1th" 1st, "12nd" 12th. Other words stay."""
    match = re.fullmatch(r"(\d+)(st|nd|rd|th)", word)
    if not match:
        return word
    n = int(match[1])
    ending = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{match[1]}{ending}"


def nearest_numbers(rows: list[tuple[str, int]], value: int) -> list[str]:
    """Of the house numbers (number, its value) a street has, the nearest on the same side as `value`
    (odd or even, as New York numbers its sides): the one just below and the one just above."""
    side = [(number, v) for number, v in rows if v is not None and v % 2 == value % 2 and v != value]
    below = max((row for row in side if row[1] < value), key=lambda row: row[1], default=None)
    above = min((row for row in side if row[1] > value), key=lambda row: row[1], default=None)
    return [row[0] for row in (below, above) if row]


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
            raise AddressError(f'not found: no street called "{street}"{where} in the address index; check how '
                               f'the street is written: {HOW_TO_WRITE}')
        rows = db.execute(f"SELECT display, borough, zip, lat, lon FROM addresses WHERE {on_street} AND number = ?",
                          (street, borough, borough, number)).fetchall()
        note = ""
        if not rows:
            value = int(number.split("-")[0])
            near = db.execute(f"SELECT DISTINCT number, number_value FROM addresses WHERE {on_street} "
                              "AND number_value BETWEEN ? AND ?",
                              (street, borough, borough, value - NEARBY, value + NEARBY)).fetchall()
            nearest = nearest_numbers(near, value)
            if not nearest:
                raise AddressError(f"not found: {street_name[0]}{where} has no number {number}, nor one near it "
                                   f"on the same side of the street")
            # The nearest; the lower of two as near.
            used = min(nearest, key=lambda n: (abs(int(n.split("-")[0]) - value), int(n.split("-")[0])))
            note = f"{number} isn't on {street_name[0]}; {used}, the nearest on the same side, is used"
            rows = db.execute(f"SELECT display, borough, zip, lat, lon FROM addresses WHERE {on_street} "
                              "AND number = ?", (street, borough, borough, used)).fetchall()
            number = used
    if len({row[1] for row in rows}) > 1:
        raise AddressError(f"unclear: {number} {rows[0][0]} is in both Brooklyn and Manhattan; add the borough")
    display, borough, zip_code, lat, lon = rows[0]
    return Place(f"{number} {display}, {borough} {zip_code}", lat, lon, note)
