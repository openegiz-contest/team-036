# SUBMISSION — OpenPit Twin

## Concept

**Enterprise:** Open-pit copper mine with two loading faces, a six-truck haulage fleet, two haul roads and a shared dump/crusher-feed point. The model is a clearly labelled synthetic reference case, not a claim to reproduce a named mine.

**Users:** Shift dispatcher, haulage supervisor and mine operations engineer.

**Decision:** Every dispatch cycle, choose which loading face should receive each available truck, considering travel distance, queue length, road restrictions, excavator availability and truck fuel. The dispatcher can compare normal operation with a road closure or an excavator outage.

**Why this choice:** Truck queues and poorly balanced assignments create avoidable waiting for both trucks and excavators. A connected fleet model makes the operational consequences visible and gives the dispatcher an actionable assignment rather than a passive dashboard.

**Real or fictional:** Fictional, inspired by conventional open-pit truck-and-shovel operations. All dimensions and cycle times are declared synthetic assumptions in `team/openpit/simulator.py`; they are intended for demonstration and must be calibrated against site dispatch logs before operational use.

## Team

| GitHub |
|---|
| <!-- Add the registered participant GitHub username(s) before submission. --> |

## Mine

The OpenPit Twin uses the OpenEgiz platform and Eclipse Ditto things in namespace `org.openegiz.openpit`. Definitions are in `team/openpit/twins.json`; state updates are published by `team/openpit/simulator.py` as Ditto protocol `modify` messages over MQTT. The platform's normal MQTT → Ditto → Telegraf → InfluxDB → Grafana pipeline is retained.

Twin types and relationships:
- `pit-01`: mine-level totals and current dispatch mode.
- `excavator-01`, `excavator-02`: loading state, queue, face grade, loaded tonnage and idle time.
- `truck-01` … `truck-06`: state, assignment, payload, speed, route progress, fuel, completed trips and wait time.
- `road-01`, `road-02`: availability, traffic factor, traffic count and estimated travel time.
- `dump-01`: received tonnage, throughput and queue.

Every equipment/road/dump twin references the pit through `attributes._parents`. Truck states progress through dispatch, travel to loader, loading, loaded haul, dumping, return and refuelling. The dispatcher assigns an available truck to the face with the lowest estimated cost; road and equipment disruptions affect that cost.

## Modules and What-if Scenarios

| Module or scenario | What it does | How to see it on the Stand | How to undo it |
|---|---|---|---|
| Haulage and dispatch | Assigns waiting trucks using queue, travel time and penalties; publishes assignments and truck states | Open OpenEgiz → Twins and Grafana → Dashboards → OpenPit Twin — Dispatch Control | Restart with `OPENPIT_SCENARIO=normal` |
| Fleet and loading model | Six trucks, two excavators, road links and dump point with connected state | Twin list; Grafana panels; simulator logs | Restart simulator |
| Spatial dispatch view | Live 2D mine map with road paths, truck markers, excavators, dump point and disruption highlighting; reads current twin state from Ditto API | Open `http://localhost:8091/` | Refreshes automatically every 2 seconds |
| What-if: road closure | `road-01` is marked closed and its travel time/dispatch cost rises; new assignments favour the other route | Launch using `OPENPIT_SCENARIO=road_closure`; inspect road and truck twins | `OPENPIT_SCENARIO=normal` |
| What-if: excavator outage | `excavator-01` reports out of service and assignments are penalized, redirecting new trucks to the second face | Launch using `OPENPIT_SCENARIO=excavator_failure`; inspect excavator and truck twins | `OPENPIT_SCENARIO=normal` |

Scenarios are selected through the simulator environment variable before launch; no code edits are needed. They are deterministic enough for repeatable demonstrations, while individual fuel levels include seeded variation.

## What works and what does not

Implemented in code: twin definitions, MQTT telemetry publisher, six-truck state machine, two loading faces, two road twins, dynamic assignment, fuel consumption/refuelling, dump throughput, and two disruption modes. The dashboard JSON is provided with panels for mine totals, truck state, queue and road travel time.

Not verified in this authoring environment: a full Docker deployment, live Ditto ingestion, Grafana panel queries and the clean Ubuntu judge run. These must be checked on the target machine using the README instructions. The model is a demonstration simulator, not a safety-critical dispatch controller.

## Data and Assumptions

No external dataset is redistributed. Synthetic assumptions: truck payload 90 t; loaded speed about 21–24 km/h; empty speed about 32 km/h; haul road lengths 2.4 km and 3.1 km; loading cycle 150 simulated seconds; dump cycle 45 simulated seconds; two loading faces and six trucks. Simulation time is accelerated for demonstration. Parameters are illustrative and should be replaced with mine-specific fleet, road, cycle-time and dispatch data for operational use.

## Mine visualization

Grafana dashboard `OpenPit Twin — Dispatch Control` is provisioned in the `OpenEgiz Examples` folder. `team/openpit/scene.py` serves a live spatial schematic at `http://localhost:8091/`; it polls Eclipse Ditto and places six truck markers on two haul routes, highlights a closed road and lists live fleet states. The OpenEgiz Twins application exposes the underlying twin states. The scene is a 2D schematic, not a surveyed or 3D terrain model.

## Limitations

The simulator uses a simplified two-route network, approximate cycle times and a heuristic dispatcher rather than a calibrated optimization solver. It does not model collision avoidance, road grades, payload variance, shift calendars, maintenance schedules, blasting exclusion zones or safety interlocks. The dashboard, spatial scene and live integration require end-to-end verification before judging. No operational decision should be based on this synthetic model.

## Presentation

See `presentation.pdf` in the repository root.
