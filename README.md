# Home-care route planner

A home-care nurse visits patients at home. Each evening they decide whom to see tomorrow and
in what order: as many visits as possible, each at a time the patient can be seen, with as
little time on the road as possible.

This project has a small language model make that plan, running entirely on the nurse's own
computer, so patient addresses never leave it. The model reads the nurse's list, finds the
addresses, and chooses the plan; a solver it can call works out the best orders, and code
checks the plan.

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
| travel_times | Walking minutes between places whose addresses were found | Done |
| best_plans | Tries every plan and gives the best few: least walking, least waiting, home earliest | Done |
| check_plan | Walks through the day in the model's order and reports the times and any broken rules | Done |

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
boroughs and the address needs one; for a street it can't find, it also says how to write an
address, with a placeholder example (with a real one, the model copied it). The model sees the address as found, not its latitude and
longitude: how far apart places are is for travel_times to say.

## Travel times

travel_times asks a road router, [OSRM](https://project-osrm.org), running locally in Docker,
for the walking time from every place the model names to every other one, in one request. It
uses the walking road network built in `data/osrm/walking` (kept out of the repository). The
model gets one line per starting place, e.g. `from home: P1 2, P2 3, P3 4`, in whole minutes.
It gives no times until every place asked about has been found: given the other places' times,
the model kept asking for travel times and never fixed the address that wasn't found.

## Rules and checking a plan

The rules are the user's, with defaults, and the model is told the same rules check_plan uses:

| Rule | Default | Option |
|---|---|---|
| Leave home at the earliest | 08:00 | `--day-start` |
| Back home by | 17:00 | `--day-end` |
| Most visits in a day | 5 | `--max-visits` |
| Length of a visit | 30 minutes | `--visit-minutes` |
| A visit may start this much before or after the patient's window | 10 minutes | `--window-slack` |

Arriving earlier than a window allows, the nurse waits; that is not a problem, but the waiting
is reported. Starting later than the window allows is a problem, as are too many visits, a
patient in the plan twice, and getting home too late.

check_plan takes the plan's order and each patient's window as the model read it from the list
(so the model still reads the list itself, and a misread window shows in the check). It walks
through the day and answers with the times and the problems; it never suggests a better order:

```
Plan check: 1 problem.
leave home 08:00
P1: walk 5 min, arrive 08:05, start 08:05, finish 08:35
P3: walk 5 min, arrive 08:40, wait 250 min, start 12:50, finish 13:20 (window 13:00-)
P2: walk 5 min, arrive 13:25, start 13:25, finish 13:55 (window -12:00): LATE, must start by 12:10
walk 5 min, back home 14:00
Total: 3 visits, 20 min walking, 250 min waiting.
Problems:
- P2 starts 75 min after its latest start (12:10).
```

submit_plan accepts any plan: checking it before handing it in is the model's job.

## Best plans

best_plans takes each patient's window as the model read it from the list, tries every order of
up to the most visits allowed, checks each one the way check_plan does, and keeps the plans with
the most visits that fit the rules. It gives the best of those by three measures, because which
is best depends on the nurse: the least walking can mean hours of waiting mid-day.

```
Best plans with 5 visits (5178 plans with 5 visits fit the rules):
- least walking: P2 -> P1 -> P3 -> P6 -> P7: walk 67 min, wait 199 min, leave 08:00, back 14:56
- least waiting, earliest home: P5 -> P1 -> P2 -> P6 -> P7: walk 77 min, wait 0 min, leave 08:00, back 11:47
Windows you gave, next to each patient's line in the list (id,name,address,earliest,latest):
P1: none | P1,Elena Russo,"6302 18th Ave, Brooklyn",,
P2: latest 12:00 | P2,Victor Huang,"1703 65th St, Brooklyn",,12:00
...
```

The plans are only as good as the model's reading: with a window misread, they are the best
plans for the wrong rules. So the answer shows each window the model gave next to the list's own
line, for the model to compare. Trying every plan is exact, and takes about 2 seconds for 12
patients; longer lists are refused.

## Commands

Run from the project root, in the project's Python environment (`.venv`). The model runs in
[Ollama](https://ollama.com): install it, then `ollama pull llama3.1:8b`. The road router runs in
Docker: start Docker, then the router.

| What | Command |
|---|---|
| Start the road router | `docker compose up -d` |
| Plan tomorrow, showing every step | `.venv/Scripts/python -m homecare.agent examples/18th_avenue.csv --home "6302 18th Ave, Brooklyn"` |
| Run the tests | `.venv/Scripts/python -m pytest` |
