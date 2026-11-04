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

1. The model reads the patient list (CSV), one row at a time: name, address, and the time window if any
2. Find each address on the map
3. Work out the travel time between home and every patient
4. The model plans tomorrow's visits
5. Check the plan; the model gets the problems back and revises it until it passes

## The patient list

A CSV with a header row and one row per patient. The columns can be named and written as the
nurse likes, because the model reads each row: `Patient, Where, When` with `after 1pm` works
as well as `name, address, earliest, latest` with `13:00`. For each row the model writes down:

| Field | Meaning |
|---|---|
| name | The patient's name |
| address | The street address, as written |
| earliest | The visit may not start before this time, if the row says so |
| latest | The visit must be over by this time, if the row says so |

Code checks what the model wrote. A time it can't read, or a window that ends before it
starts, goes back to the model with the mistake for another try (three tries in all).

See [examples/patients.csv](examples/patients.csv). [examples/18th_avenue.csv](examples/18th_avenue.csv)
has ten patients around 18th Avenue in Brooklyn: from a home at 6302 18th Ave, five are within a
few blocks of each other, and the best day visits exactly those five.

## Commands

Run from the project root, in the project's Python environment (`.venv`). The model runs in
[Ollama](https://ollama.com): install it, then `ollama pull llama3.1:8b`.

| What | Command |
|---|---|
| Show how the model reads a patient list | `.venv/Scripts/python -m homecare.patients examples/patients.csv` |
| Run the tests | `.venv/Scripts/python -m pytest` |
