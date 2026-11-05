# Home-care route planner

A home-care nurse visits patients at home. Each evening they decide whom to see tomorrow and
in what order: as many visits as possible, each at a time the patient can be seen, with as
little time on the road as possible.

This project has a small language model make that plan, running entirely on the nurse's own
computer, so patient addresses never leave it. The model chooses the patients and their
order; code only gives it facts (where an address is, how long a trip takes) and checks its
plan.

> Status: being rebuilt one step at a time. Patient data in this repository is made up.

## An agent, not a pipeline

The model works in a loop. At each step it writes its thinking and picks one action, a tool;
code runs the tool and gives it the result; the model picks the next action, until it submits
a plan. Code never decides what happens next. It only runs the tools, which give facts and
check plans but never choose or order patients, and stops a model that runs past 20 steps.

Each step is JSON that must follow a schema (Ollama's structured outputs). The schema has one
shape per tool (`anyOf`): thinking first, then the tool's name as the action, then that tool's
own fields only:

```json
{"thinking": "...", "action": "travel_times", "between": ["home", "P1", "P2"]}
{"thinking": "...", "action": "submit_plan", "order": ["P3", "P1", "P2"]}
```

An earlier version put every tool's fields in one shape and asked the model to leave the others
empty. The model then wrote travel_times' places into find_address's `places` field, and left
`between` empty. Lists also have a smallest size (`minItems`), because the model often wrote an
empty list when unsure.

| Tool | What it does | Status |
|---|---|---|
| submit_plan | Hands in the plan and finishes | Done |
| find_address | Finds where addresses are on the map, for patients (by id) and home | Done |
| travel_times | Walking minutes between places whose addresses were found | Done |
| check_plan | Checks a plan against the time windows, the visit limit and the working day, and totals its travel | Next |

## The patient list

A CSV with a header row and one row per patient. The model gets the list as it is, with an id
column in front (P1, P2, ...) so it can name each patient exactly, and reads it itself: the
columns can be named and written as the nurse likes, e.g. `Patient, Where, When` with
`after 1pm`. Each patient needs a name, an address, and optionally a time window.

See [examples/patients.csv](examples/patients.csv). [examples/18th_avenue.csv](examples/18th_avenue.csv)
has ten patients around 18th Avenue in Brooklyn: from a home at 6302 18th Ave, five are within a
few blocks of each other, and the best day visits exactly those five.

## Finding addresses

find_address looks addresses up in an offline index of Brooklyn and Manhattan addresses,
`data/addresses.db` (kept out of the repository; a SQLite table of house number, street,
borough, zip, latitude and longitude). It reads short forms (`Ave`, `St`, `Pkwy`, `E` for East,
...) and finds an address only if its house number and street match exactly: it never guesses.
It tells the model when a street or house number isn't in the index, or when a street is in both
boroughs and the address needs one. The model sees the address as found, not its latitude and
longitude: how far apart places are is for travel_times to say.

## Travel times

travel_times asks a road router, [OSRM](https://project-osrm.org), running locally in Docker,
for the walking time from every place the model names to every other one, in one request. It
uses the walking road network built in `data/osrm/walking` (kept out of the repository). The
model gets one line per starting place, e.g. `from home: P1 2, P2 3, P3 4`, in whole minutes.

## Commands

Run from the project root, in the project's Python environment (`.venv`). The model runs in
[Ollama](https://ollama.com): install it, then `ollama pull llama3.1:8b`. The road router runs in
Docker: start Docker, then the router.

| What | Command |
|---|---|
| Start the road router | `docker compose up -d` |
| Plan tomorrow, showing every step | `.venv/Scripts/python -m homecare.agent examples/18th_avenue.csv --home "6302 18th Ave, Brooklyn"` |
| Run the tests | `.venv/Scripts/python -m pytest` |
