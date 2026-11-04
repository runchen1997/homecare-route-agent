# Home-care route planner

A home-care nurse visits patients at home. Each evening they decide whom to see tomorrow and
in what order: as many visits as possible, each at a time the patient can be seen, with as
little time on the road as possible.

This project has a small language model make that plan, running entirely on the nurse's own
computer, so patient addresses never leave it. The model chooses the patients and their
order; code only gives it facts (where an address is, how long a trip takes) and checks its
plan.

> Status: being rebuilt one step at a time. Patient data in this repository is made up.

## First version

1. Read the patient list (CSV): name, address, and an optional time window
2. Find each address on the map
3. Work out the travel time between home and every patient
4. The model plans tomorrow's visits
5. Check the plan; the model gets the problems back and revises it until it passes

## The patient list

| Column | Meaning |
|---|---|
| name | The patient's name |
| address | Street address, e.g. `6502 18th Ave, Brooklyn` |
| earliest | Optional: the visit may not start before this time (`HH:MM`) |
| latest | Optional: the visit must be over by this time (`HH:MM`) |

See [examples/patients.csv](examples/patients.csv). [examples/18th_avenue.csv](examples/18th_avenue.csv)
has ten patients around 18th Avenue in Brooklyn: from a home at 6302 18th Ave, five are within a
few blocks of each other, and the best day visits exactly those five.

## Commands

Run from the project root, in the project's Python environment (`.venv`):

| What | Command |
|---|---|
| Show how a patient list is read | `.venv/Scripts/python -m homecare.patients examples/patients.csv` |
| Run the tests | `.venv/Scripts/python -m pytest` |
