# Home-care route planner

A home-care nurse visits patients at home. Each evening they decide whom to see tomorrow and
in what order: as many visits as possible, each at a time the patient can be seen, with as
little time on the road as possible.

This project has a small language model make that plan, running entirely on the nurse's own
computer, so patient addresses never leave it. The model reads the nurse's list, finds the
addresses, and chooses the plan; a solver it can call works out the best orders, and code
checks the plan. The nurse uses it from a web page with a map of the day, on the same computer.

> Status: being rebuilt one step at a time. Patient data in this repository is made up.

## An agent, not a pipeline

The model works in a loop. At each step it writes its thinking and picks one action, a tool;
code runs the tool and gives it the result; the model picks the next action, until it submits
a plan. Code never decides what happens next. It only runs the tools, and stops a model that
runs past 20 steps.

### Why a solver: a hybrid

At first the model also worked out the order itself, with tools that only gave facts and
checked plans. It handed in plans that fit the rules but walked 18-33% more than the best plan:
choosing 5 of 8 patients and their order means searching thousands of plans, and a small model
picks the first plan that fits. So the search is now a tool, best_plans, and the model does what
it is better at than a solver: reading a list written any way (`after 1pm`, `1025 70th bk`),
choosing among good plans by what the nurse prefers, and explaining.

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
| travel_times | Travel minutes, walking or driving, between places whose addresses were found | Done |
| best_plans | Tries every plan and gives the best few: least travel, least waiting, home earliest | Done |
| check_plan | Walks through the day in the model's order and reports the times and any broken rules | Done |

## The patient list

A CSV with a header row and one row per patient. The model reads it itself: the columns can be
named and written as the nurse likes, e.g. `Patient, Where, When` with `after 1pm`. Each patient
needs a name, an address, and optionally a time window.

The model gets one line per patient, with an id (P1, P2, ...) so it can name each patient
exactly, and each cell under its column's name, an empty one written as `(empty)`:

```
P2: name: Victor Huang; address: 1703 65th St, Brooklyn; earliest: (empty); latest: 12:00
```

Nothing is read for it; this only saves it counting commas. Given the CSV as it is, the model
often read `...,,12:00` (latest 12:00) as earliest 12:00, and whether it did changed with any
small change elsewhere in the prompt.

See [examples/patients.csv](examples/patients.csv). [examples/18th_avenue.csv](examples/18th_avenue.csv)
has ten patients around 18th Avenue in Brooklyn: from a home at 6302 18th Ave, five are within a
few blocks of each other, and the best day visits exactly those five.

## Finding addresses

find_address looks addresses up in an offline index of Brooklyn and Manhattan addresses,
`data/addresses.db` (kept out of the repository; a SQLite table of house number, street,
borough, zip, latitude and longitude). It reads short forms (`Ave`, `St`, `Pkwy`, `E` for East,
...) and finds an address only if its house number and street match exactly: it never guesses.
It tells the model when a street or house number isn't in the index, or when a street is in both
boroughs and the address needs one; for a street it can't find, it also says how to write an
address, with a placeholder example (with a real one, the model copied it). The model sees the address as found, not its latitude and
longitude: how far apart places are is for travel_times to say.

## Travel times

The nurse walks, drives, or takes the subway and bus (`--mode walking`, `driving` or `transit`;
walking by default), and the model is told which. On foot or by car, travel_times asks a road router, [OSRM](https://project-osrm.org), running
locally in Docker, for the travel time from every place the model names to every other one, in
one request. There is one router per way of travelling, each with its road network built in
`data/osrm/walking` or `data/osrm/driving` (kept out of the repository). The model gets one line
per starting place, e.g. `from home: P1 2, P2 3, P3 4`, in whole minutes.

The code keeps travel times in seconds, and shows minutes only in what the model and the nurse
read. Plans are compared by adding up a day's legs, and with each leg rounded to a minute first,
a 13-second drive counted as 0 and 23 different plans for a list tied at 10 minutes; the one
picked drove 37 seconds more than the shortest.

Driving times are OSRM's: no traffic, and no time to find a place to park, so they are too short
for a city. For the map, the same router also gives the way along the streets for each leg of the
plan (`travel.route`). From the home on 70th St, the patients in `examples/patients.csv` are 20-31 minutes
away on foot and 3-6 by car.
It gives no times until every place asked about has been found: given the other places' times,
the model kept asking for travel times and never fixed the address that wasn't found.

### By subway and bus

By subway and bus, the times come from [R5](https://github.com/conveyal/r5), Conveyal's routing
engine for public transport, run through [r5py](https://r5py.readthedocs.io): the streets of
Brooklyn and Manhattan with the MTA's subway and bus timetables (GTFS, in `data/gtfs`), walking to
the stop, between stops and from the last one, or all the way where that is quicker. Ferries are
never used. R5 runs in Java inside the planner, and starts only for a nurse who travels this way:
the first time, building the network takes about 75 seconds, and it is kept in `data/r5` (900 MB)
to read back in about 15 after that. Everything R5 writes goes there.

How long a trip by subway and bus takes depends on when it starts: how long the wait for the next
train or bus is. The planner uses typical times: for each pair of places, the median over
departures through the nurse's working day, on the day planned for (tomorrow, or `--date`), since
weekday and weekend timetables differ. Each table takes about 9 seconds. R5 gives whole minutes,
and walks at the walking router's 5 km/h (its own is 3.6), so walking times are the same either way.
From 70th St the patients in `examples/patients.csv` are 18-27 minutes away by subway and bus
(19-39 on foot), and the Upper West Side 67 minutes (4 hours on foot). The timetables run to a last
day (the buses' to 2 January 2027): a day after that is refused, with a note to download newer ones.

## Rules and checking a plan

The rules are the user's, with defaults, and the model is told the same rules check_plan uses:

| Rule | Default | Option |
|---|---|---|
| Leave home at the earliest | 08:00 | `--day-start` |
| Back home by | 17:00 | `--day-end` |
| Most visits in a day | 5 | `--max-visits` |
| Length of a visit | 30 minutes | `--visit-minutes` |
| A visit may start this much before or after the patient's window | 10 minutes | `--window-slack` |
| Longest working day, from leaving home to getting back | no limit | `--work-hours` |
| Longest wait at a patient's door | 20 minutes | `--max-wait` |
| Best plan, among those with as many visits | least travel | `--prefer` (`least travel` or `tightest group`) |

The nurse sets how much work the day holds: how many visits (`--max-visits`), or how long the
day may be (`--day-start` and `--day-end` for a time of day, `--work-hours` for a length), or
both. Within that, the plan has as many visits as fit, then what the nurse prefers: the least
travel in the whole day, or the tightest group of patients, the least travel from one patient to
the next. They differ when some patients live near home and the rest close together farther
away: the least travel picks the ones on the way, and the tightest group the ones together, for a
few minutes more (from 1025 70th St, `examples/18th_avenue.csv` takes 10.3 minutes' driving with
3.2 between patients, or 11.3 with 2.3). A group close together is easier to rearrange when a
visit runs long or is cancelled.

The nurse leaves home as late as the plan allows: as late as lets every visit start within its
window, without getting home later. So the nurse waits at home rather than at a door, and the
working day is no longer than the plan needs. Waiting that can't be avoided (between a visit
that must be early and one that can't start until later) is reported, and counts toward the
working day; a wait longer than `--max-wait` at any door is a problem. Starting later than the
window allows is a problem, as are too many visits, a patient in the plan twice, getting home too
late, and too long a day.

check_plan takes the plan's order and each patient's window as the model read it from the list
(so the model still reads the list itself, and a misread window shows in the check). It walks
through the day and answers with the times and the problems; it never suggests a better order:

```
Plan check: 1 problem.
leave home 12:10
P1: travel 5 min, arrive 12:15, start 12:15, finish 12:45
P3: travel 5 min, arrive 12:50, start 12:50, finish 13:20 (window 13:00-)
P2: travel 5 min, arrive 13:25, start 13:25, finish 13:55 (window -12:00): LATE, must start by 12:10
travel 5 min, back home 14:00
Total: 3 visits, 20 min travel, 0 min waiting, working day 1 h 50 min.
Problems:
- P2 starts 75 min after its latest start (12:10).
```

submit_plan accepts any plan: checking it before handing it in is the model's job. With the
plan, the model writes its reasons for the nurse, in a sentence or two; they are printed at the end.

## Best plans

best_plans takes each patient's window as the model read it from the list, tries every order of
up to the most visits allowed, checks each one the way check_plan does, and keeps the plans with
the most visits that fit the rules. It gives the best of those by four measures: the least
travel, the tightest group, the least waiting, and home earliest. The one the nurse prefers comes
first, and is marked; the others are there because the least travel can mean getting home hours
later, and so the model can say what the nurse's choice costs.

```
Best plans with 5 visits (5165 plans with 5 visits fit the rules):
- least travel (the nurse's preference): P2 -> P3 -> P1 -> P6 -> P7: travel 68 min (24 between patients), wait 4 min, leave 11:46, back 15:28
- tightest group: P7 -> P6 -> P2 -> P1 -> P3: travel 70 min (20 between patients), wait 0 min, leave 10:10, back 13:50
- least waiting: P2 -> P1 -> P3 -> P6 -> P7: travel 69 min (25 between patients), wait 0 min, leave 11:18, back 14:57
- earliest home: P5 -> P1 -> P2 -> P6 -> P7: travel 77 min (29 between patients), wait 0 min, leave 08:00, back 11:47
Windows you gave, next to each patient's line in the list:
P1: none | list: P1: name: Elena Russo; address: 6302 18th Ave, Brooklyn; earliest: (empty); latest: (empty)
P2: latest 12:00 | list: P2: name: Victor Huang; address: 1703 65th St, Brooklyn; earliest: (empty); latest: 12:00
...
```

(`examples/patients.csv`, walking from 1025 70th St.) The least travel and the least waiting are
21 seconds of walking apart here.

The plans are only as good as the model's reading: with a window misread, they are the best
plans for the wrong rules. So the answer shows each window the model gave next to the list's own
line, for the model to compare. Trying every plan is exact, and takes about 3 seconds for 12
patients and 14 for 15 (360,000 plans of 5 visits); longer lists are refused.

## The nurse's page

The nurse plans from a web page that runs on their own computer: they choose the patient list,
type their home address, pick walking or driving and how much work the day holds, and press
*Plan tomorrow*. A plan takes 20-35 seconds, so the page shows each step as the model takes it:
its thinking, the tool it used, and what the tool answered. When the model hands in its plan,
the page shows the day: when to leave, each visit in order with its times and window, when the
nurse is home, the model's reasons, and the patients not visited. Next to it, a map draws the
route along the streets, with home, each visit numbered in order, and the patients not visited
in grey.

Nothing on the page leaves the computer. The planner is a web service, `homecare/web.py`
(FastAPI), that listens on 127.0.0.1 only, and serves the page, the planner and the map:

| Path | What |
|---|---|
| `POST /api/plan` | Plans tomorrow. The answer is a stream of Server-Sent Events: a `step` for each step the model takes, then `plan` (the schedule, the places, the route) or `error` |
| `GET /api/examples` | The sample patient lists, each with a home to plan from |
| `/map-data/...` | The map's streets, fonts and icons, from `data/map` |
| `/` | The page, once built |

The schedule on the page is the model's plan checked again, with the windows the model gave, by
the same checker check_plan uses; the route is OSRM's, for the way the nurse travels. One plan is
worked out at a time, since the model has one graphics card.

The page itself is React, built with Vite, in `frontend/`.

### An offline map

The map is drawn with [MapLibre GL JS](https://maplibre.org) from a map file on this computer,
not from map tiles on the internet: asking a tile server for the map around the nurse's patients
would tell it where they are. The file, `data/map/nyc.pmtiles` (49 MB, kept out of the
repository), holds the streets of Brooklyn and Manhattan, where the address index is, in
[PMTiles](https://protomaps.com/docs/pmtiles) form: one file the page reads a piece at a time,
with HTTP range requests. It was cut from [Protomaps](https://protomaps.com)' daily map of the
world, which is made from [OpenStreetMap](https://www.openstreetmap.org/copyright) data; the
map shows that credit. Its fonts and icons are in `data/map` too, and the map follows the
computer's light or dark setting.

## Evaluation

`evals/` runs the planner on a fixed set of 24 cases and scores every plan the same way. The cases
use five patient lists: the three in `examples/`, one in Manhattan with each window in a single
column (`09:00-11:00`, `by 12:00`), and one in Bay Ridge with the columns in another order, the
times among other notes (`call first; between 1 and 3pm`), and an address the index can't find as
written (`6901 Third Avenue, Bay Ridge`). Across them the cases change how home is written,
walking or driving, the workload (most visits, longest day, back by a time) and the nurse's
preference.

Each list comes with its true windows, and each case's answer key is worked out by best_plans
with those, not with the model's reading: the plan best by the nurse's preference, in seconds.
The model's plan is then checked against the true windows, and scored apart on each count:

| Count | First run (24 cases, llama3.1:8b) |
|---|---|
| The best plan, by the nurse's preference | 24/24 |
| Fits the rules, with the true windows | 24/24 |
| Every address found | 24/24 |
| Every window read as the list means it | 19/24 (214 of 220 windows) |
| Steps | 5.8 on average; 13 wasted in all (a tool refused the call, or it repeated one) |
| Time | 29 s on average |

The windows read wrong were read in a way that didn't change the plan (`by 12:00` read as from
12:00, for a patient visited in time anyway); the nurse is expected to write windows plainly. Most
of the wasted calls asked for travel times before every address was found. The results, one line
per case, are in `evals/results/`.

## Commands

Run from the project root, in the project's Python environment (`.venv`). The model runs in
[Ollama](https://ollama.com): install it, then `ollama pull llama3.1:8b`. The road routers run in
Docker: start Docker, then the routers. The page needs [Node.js](https://nodejs.org) to build.

| What | Command |
|---|---|
| Start the road routers, for walking and driving | `docker compose up -d` |
| Build the page (once, and after changing it) | `cd frontend && npm install && npm run build` |
| Start the planner and its page, then open http://127.0.0.1:8000 | `.venv/Scripts/python -m homecare.web` |
| Work on the page, reloading as it changes (with the planner running), at http://127.0.0.1:5173 | `cd frontend && npm run dev` |
| Plan tomorrow in the terminal, showing every step | `.venv/Scripts/python -m homecare.agent examples/18th_avenue.csv --home "6302 18th Ave, Brooklyn"` |
| The same, for a working day of at most 3.5 hours | `.venv/Scripts/python -m homecare.agent examples/patients.csv --home "1025 70th St, Brooklyn" --work-hours 3.5` |
| The same, driving | `.venv/Scripts/python -m homecare.agent examples/patients.csv --home "1025 70th St, Brooklyn" --mode driving` |
| The same, by subway and bus, on a given day | `.venv/Scripts/python -m homecare.agent examples/patients.csv --home "1025 70th St, Brooklyn" --mode transit --date 2026-11-09` |
| Run the tests | `.venv/Scripts/python -m pytest` |
| Run the evaluation (about 12 minutes), or only some cases | `.venv/Scripts/python -m evals.run`, `... --cases bay_ridge` |
| See every case's answer key | `.venv/Scripts/python -m evals.keys` |

### Making the offline map

The map's files are downloaded once, into `data/map`:

1. The map file. Download `pmtiles.exe` from the [go-pmtiles releases](https://github.com/protomaps/go-pmtiles/releases)
   (into `tools/pmtiles`), and cut Brooklyn and Manhattan out of a daily Protomaps build (any date listed at
   [maps.protomaps.com/builds](https://maps.protomaps.com/builds)). It reads only the part of the world file it needs:
   `tools/pmtiles/pmtiles.exe extract https://build.protomaps.com/20261106.pmtiles data/map/nyc.pmtiles --bbox=-74.06,40.55,-73.83,40.89 --maxzoom=15`
2. The fonts and icons, from [protomaps/basemaps-assets](https://github.com/protomaps/basemaps-assets): the folders
   `fonts/Noto Sans Regular`, `fonts/Noto Sans Medium` and `fonts/Noto Sans Italic` into `data/map/fonts`, and
   `sprites/v4/light*` and `sprites/v4/dark*` into `data/map/sprites/v4`.
