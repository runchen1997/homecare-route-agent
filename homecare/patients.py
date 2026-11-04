"""Read the nurse's patient list: the language model reads each row of the CSV.

The CSV needs one row per patient, with a header row; its columns can be named and written as
the nurse likes. For each row the model writes down the patient's name, address, and the time
window the row gives, if any. Code only splits the file into rows and checks what the model
wrote: a time that isn't a time, or a window that ends before it starts, goes back to the model
with the mistake, for another try.

Run it to see how a list is read (Ollama must be running):
    python -m homecare.patients examples/patients.csv
"""

import csv
import dataclasses
import json
import re
import sys

from homecare import llm

READ_PROMPT = """\
You read one row of a home-care nurse's patient list and write down what it says:
- name: the patient's name.
- address: the street address, as written.
- earliest: the earliest time the visit may start, as HH:MM in 24-hour time; "" if the row gives none.
- latest: the time the visit must be over by, as HH:MM in 24-hour time; "" if the row gives none.
Write only what the row says. Never guess a time the row doesn't give."""

# Rows the model is shown with the answer it should give, before the real row.
EXAMPLES = [
    ("name: Ana Diaz\naddress: 12 Main St, Brooklyn\nearliest: \nlatest: 11:30",
     {"name": "Ana Diaz", "address": "12 Main St, Brooklyn", "earliest": "", "latest": "11:30"}),
    ("Patient: Tom Lee\nAddr: 455 5th Ave apt 2\nVisit window: after 2pm",
     {"name": "Tom Lee", "address": "455 5th Ave apt 2", "earliest": "14:00", "latest": ""}),
]

READ_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "address": {"type": "string"},
        "earliest": {"type": "string"},
        "latest": {"type": "string"},
    },
    "required": ["name", "address", "earliest", "latest"],
}
TRIES = 3  # answers the model may give for one row before the row is given up on


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


def clock(value: int | None) -> str:
    """780 -> '13:00'; None -> ''."""
    return "" if value is None else f"{value // 60:02d}:{value % 60:02d}"


def rows(path: str) -> list[str]:
    """Each row of the CSV as text for the model, one "column: value" line per cell."""
    with open(path, encoding="utf-8", newline="") as file:
        table = list(csv.DictReader(file))
    if not table:
        raise ValueError(f"{path} has no patients")
    return ["\n".join(f"{column}: {(value or '').strip()}" for column, value in row.items()) for row in table]


def patient_from(answer: dict, id_: str) -> Patient:
    """The patient the model wrote down, if what it wrote makes sense."""
    name, address = answer["name"].strip(), answer["address"].strip()
    if not name or not address:
        raise ValueError("every patient needs a name and an address")
    earliest, latest = minutes(answer["earliest"]), minutes(answer["latest"])
    if earliest is not None and latest is not None and earliest >= latest:
        raise ValueError("earliest must come before latest")
    return Patient(id_, name, address, earliest, latest)


def read_patient(row: str, id_: str, ask=llm.ask) -> Patient:
    """The model's reading of one row; a mistake goes back to it, up to TRIES answers in all."""
    messages = [{"role": "system", "content": READ_PROMPT}]
    for example_row, example_answer in EXAMPLES:
        messages += [{"role": "user", "content": example_row},
                     {"role": "assistant", "content": json.dumps(example_answer)}]
    messages.append({"role": "user", "content": row})
    for _ in range(TRIES):
        try:
            answer = ask(messages, READ_SCHEMA, 200)
        except llm.CutOff:
            continue
        try:
            return patient_from(answer, id_)
        except ValueError as error:
            messages += [{"role": "assistant", "content": json.dumps(answer)},
                         {"role": "user", "content": f"Error: {error}. Answer again."}]
    raise ValueError(f"couldn't read {id_}'s row:\n{row}")


def read_patients(path: str, ask=llm.ask) -> list[Patient]:
    """Every patient in the CSV at `path`, read by the model one row at a time."""
    return [read_patient(row, f"P{number}", ask) for number, row in enumerate(rows(path), start=1)]


if __name__ == "__main__":
    for patient in read_patients(sys.argv[1]):
        window = f"{clock(patient.earliest) or 'any time'} - {clock(patient.latest) or 'any time'}"
        print(f"{patient.id:4} {patient.name:18} {patient.address:32} {window}")
