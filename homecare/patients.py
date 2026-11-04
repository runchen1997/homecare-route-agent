"""Read the nurse's patient list: a CSV with one row per patient.

Columns:
  name      the patient's name
  address   street address, e.g. "6502 18th Ave, Brooklyn"
  earliest  optional: the visit may not start before this time, e.g. "13:00"
  latest    optional: the visit must be over by this time, e.g. "12:00"

Run it to see how a list is read:
    python -m homecare.patients examples/patients.csv
"""

import csv
import dataclasses
import re
import sys

COLUMNS = ["name", "address", "earliest", "latest"]


@dataclasses.dataclass
class Patient:
    id: str  # P1, P2, ... in the order of the list
    name: str
    address: str
    earliest: int | None = None  # minutes after midnight, so 13:00 is 780
    latest: int | None = None


def minutes(text: str) -> int | None:
    """'13:00' -> 780; an empty cell -> None."""
    text = text.strip()
    if not text:
        return None
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if not match or int(match[1]) > 23 or int(match[2]) > 59:
        raise ValueError(f"{text!r} is not a time; write it as HH:MM, e.g. 13:00")
    return int(match[1]) * 60 + int(match[2])


def read_patients(path: str) -> list[Patient]:
    """Every patient in the CSV at `path`; a mistake in the file stops it with the row to fix."""
    with open(path, encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    if not rows:
        raise ValueError(f"{path} has no patients")
    missing = [column for column in COLUMNS if column not in rows[0]]
    if missing:
        raise ValueError(f"{path} has no column {', '.join(missing)}; the columns are {', '.join(COLUMNS)}")

    patients = []
    for number, row in enumerate(rows, start=1):
        where = f"row {number} ({row['name'] or 'no name'})"
        if not row["name"].strip() or not row["address"].strip():
            raise ValueError(f"{where}: every patient needs a name and an address")
        try:
            earliest, latest = minutes(row["earliest"]), minutes(row["latest"])
        except ValueError as error:
            raise ValueError(f"{where}: {error}") from None
        if earliest is not None and latest is not None and earliest >= latest:
            raise ValueError(f"{where}: earliest must come before latest")
        patients.append(Patient(f"P{number}", row["name"].strip(), row["address"].strip(), earliest, latest))
    return patients


def clock(value: int | None) -> str:
    """780 -> '13:00'; None -> ''."""
    return "" if value is None else f"{value // 60:02d}:{value % 60:02d}"


if __name__ == "__main__":
    for patient in read_patients(sys.argv[1]):
        window = f"{clock(patient.earliest) or 'any time'} - {clock(patient.latest) or 'any time'}"
        print(f"{patient.id:4} {patient.name:18} {patient.address:32} {window}")
