"""The cases the planner is evaluated on.

Each patient list comes with its true windows: what the list means, written as HH:MM, so a plan
can be checked against what the patients said, not against the model's reading. The lists are
made up; the addresses are real buildings.

The lists differ in what they ask of the model's reading:
- patients, 18th_avenue: earliest and latest columns, HH:MM
- messy: one When column, written any way ("before noon", "after 1pm")
- upper_west_side: Manhattan, one Window column ("09:00-11:00", "from 13:00", "by 12:00")
- bay_ridge_messy: columns in another order, times in a notes column with other notes ("call
  first; between 1 and 3pm"), and an address the index can't find as written
  ("6901 Third Avenue, Bay Ridge"; it is 6901 3rd Ave, Brooklyn)
"""

import csv
import dataclasses
import datetime
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
NONE = ("", "")  # no window


@dataclasses.dataclass(frozen=True)
class PatientList:
    path: str  # relative to the project root
    truth: dict[str, tuple[str, str]]  # each patient's (earliest, latest) as HH:MM, "" for none
    # Addresses as the address index finds them, where the list doesn't write them that way.
    found: dict[str, str] = dataclasses.field(default_factory=dict)

    def text(self) -> str:
        return (ROOT / self.path).read_text(encoding="utf-8")


def from_columns(path: str) -> PatientList:
    """A list whose earliest and latest columns are already HH:MM: they are the truth."""
    with open(ROOT / path, encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    return PatientList(path, {f"P{i}": (row["earliest"].strip(), row["latest"].strip())
                              for i, row in enumerate(rows, 1)})


LISTS = {
    "patients": from_columns("examples/patients.csv"),
    "18th_avenue": from_columns("examples/18th_avenue.csv"),
    "messy": PatientList("examples/messy.csv", {
        "P1": NONE, "P2": ("", "12:00"), "P3": ("13:00", ""), "P4": NONE,
        "P5": NONE, "P6": ("10:00", "15:00"), "P7": NONE, "P8": NONE}),
    "upper_west_side": PatientList("evals/lists/upper_west_side.csv", {
        "P1": ("09:00", "11:00"), "P2": NONE, "P3": ("13:00", ""), "P4": ("", "12:00"), "P5": ("10:00", "14:00"),
        "P6": NONE, "P7": ("14:00", "16:00"), "P8": NONE, "P9": ("", "10:30"), "P10": NONE}),
    "bay_ridge_messy": PatientList("evals/lists/bay_ridge_messy.csv", {
        "P1": ("09:00", "11:00"), "P2": ("14:30", ""), "P3": ("", "10:00"), "P4": NONE, "P5": NONE,
        "P6": ("13:00", "15:00"), "P7": ("", "11:00"), "P8": ("10:30", ""), "P9": ("", "12:00"),
        "P10": ("14:00", "16:00")},
        found={"P4": "6901 3rd Ave, Brooklyn"}),
}

# The day every case is planned for, so that subway and bus times are the same from run to run: a Monday.
DATE = datetime.date(2026, 11, 9)

H70, H18 = "1025 70th St, Brooklyn", "6302 18th Ave, Brooklyn"
UWS, BAY_RIDGE = "250 W 85th St, Manhattan", "7501 4th Ave, Brooklyn"


@dataclasses.dataclass(frozen=True)
class Case:
    name: str
    patients: str  # a key of LISTS
    home: str  # as the nurse writes it
    mode: str = "walking"
    rules: dict = dataclasses.field(default_factory=dict)  # checking.Rules fields; the rest keep their defaults
    home_found: str = ""  # the home as the address index finds it, when `home` isn't written that way

    @property
    def home_address(self) -> str:
        return self.home_found or self.home


CASES = [
    Case("patients", "patients", H70),
    Case("patients, home as '1025 70th bk'", "patients", "1025 70th bk", home_found=H70),
    Case("patients, driving", "patients", H70, "driving"),
    Case("patients, at most 3.5 hours", "patients", H70, rules={"work_hours": 3.5}),
    Case("patients, at most 3 visits", "patients", H70, rules={"max_visits": 3}),
    Case("patients, back by 12:00", "patients", H70, rules={"day_end": "12:00"}),
    Case("patients, tightest group", "patients", H70, rules={"prefer": "tightest group"}),
    Case("patients, subway and bus", "patients", H70, "transit"),
    Case("18th_avenue", "18th_avenue", H18),
    Case("18th_avenue, from 70th St, driving", "18th_avenue", H70, "driving"),
    Case("18th_avenue, from 70th St, driving, tightest group", "18th_avenue", H70, "driving",
         rules={"prefer": "tightest group"}),
    Case("18th_avenue, at most 3 visits", "18th_avenue", H18, rules={"max_visits": 3}),
    Case("messy", "messy", H70),
    Case("messy, driving", "messy", H70, "driving"),
    Case("messy, at most 3 hours", "messy", H70, rules={"work_hours": 3}),
    Case("upper_west_side", "upper_west_side", UWS),
    Case("upper_west_side, driving", "upper_west_side", UWS, "driving"),
    Case("upper_west_side, tightest group", "upper_west_side", UWS, rules={"prefer": "tightest group"}),
    Case("upper_west_side, at most 3 visits", "upper_west_side", UWS, rules={"max_visits": 3}),
    Case("upper_west_side, subway and bus", "upper_west_side", UWS, "transit"),
    Case("upper_west_side, at most 2.5 hours", "upper_west_side", UWS, rules={"work_hours": 2.5}),
    Case("bay_ridge_messy", "bay_ridge_messy", BAY_RIDGE),
    Case("bay_ridge_messy, driving", "bay_ridge_messy", BAY_RIDGE, "driving"),
    Case("bay_ridge_messy, tightest group", "bay_ridge_messy", BAY_RIDGE, rules={"prefer": "tightest group"}),
    Case("bay_ridge_messy, back by 11:00", "bay_ridge_messy", BAY_RIDGE, rules={"day_end": "11:00"}),
    Case("bay_ridge_messy, at most 3 visits", "bay_ridge_messy", BAY_RIDGE, rules={"max_visits": 3}),
    Case("bay_ridge_messy, subway and bus, tightest group", "bay_ridge_messy", BAY_RIDGE, "transit",
         rules={"prefer": "tightest group"}),
]
