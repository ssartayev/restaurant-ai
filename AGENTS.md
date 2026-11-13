# AGENTS.md — project guide for people and for any coding model

This file is the single source of orientation for this repository. It is written to be
followed by any developer or any LLM coding assistant (Claude, GPT, Gemini, Llama, Cursor,
Copilot, Codex and others): it uses plain Markdown, assumes no tool-specific features, and
every instruction is a shell command or a file path. `CLAUDE.md` only points here.

Contents: 1 What this is · 2 Quick start · 3 Repository map · 4 Rules that must not be
broken · 5 Core algorithms and logic · 6 How to change things safely · 7 What is verified
and what is not · 8 Remaining tasks.

---

## 1. What this is

A restaurant table management service. A fixed camera watches the tables; a vision worker
turns person detections into table-level events; the API runs a table state machine
(**Ready → Occupied → Needs clearing → Ready**); a browser dashboard shows the floor, raises
a "needs clearing" alert, and suggests the next waiting party when a table is ready. Staff
can always run everything by hand.

```
camera ─RTSP─▶ edge worker ─HTTPS JSON events─▶ API ─▶ state machine ─▶ database
              (apps/worker)                    (apps/api)                  │
                                                  ▲  │ Server-Sent Events  ▼
                              staff commands ─────┘  └────────▶ web dashboard (apps/web)
```

Video never leaves the restaurant and is never stored. Only JSON like
`{"table_id": "...", "occupied": false, "observed_at": "..."}` crosses the network.

The full product and delivery plan is in `docs/PLAN.md`.

## 2. Quick start

Requirements: Python 3.11+, Node 20+, `make`. No database server is needed for development
(SQLite file); production uses PostgreSQL through `DATABASE_URL`.

```bash
make setup      # create .venv, install API, worker and web dependencies
make dev        # build the web app and serve everything on http://localhost:8000
```

Open http://localhost:8000 and press **Start demo**, or sign in with a seeded account:
`admin@demo.test / demo-admin`, `host@demo.test / demo-host`, `staff@demo.test / demo-staff`.

| Command | What it does | Expected result |
|---|---|---|
| `make test` | API tests, worker tests, web type-check | 59 + 21 tests pass, no type errors |
| `make e2e` | Browser test of the whole demo path (needs Playwright with Chromium) | `E2E passed: 10 steps` |
| `make cv-eval` | Vision evaluation on the held-out split | writes `eval/report.md` |
| `make simulate SCENARIO=dinner_basic` | Replays a scenario over HTTP against `make dev` | `all expectations met` (needs a fresh `dev.db`: run `make clean` first) |
| `make openapi` | Regenerates `packages/contracts/openapi.json` | CI fails if this file is stale |
| `make web` + `make api` | Vite hot reload on :5173 with the API on :8000 | |

Configuration is by environment variable; all of them with defaults are in
`apps/api/app/config.py`.

## 3. Repository map

| Path | Purpose | Start reading at |
|---|---|---|
| `packages/contracts/transitions.yaml` | **The state machine contract.** Tests check the code against every row | the whole file (60 lines) |
| `packages/contracts/events/*.schema.json` | Event and heartbeat payloads (JSON Schema, no extra fields allowed) | |
| `packages/contracts/openapi.json` | Generated HTTP contract | |
| `apps/api/app/state_machine.py` | Pure decision functions: no database, no clock | `decide_camera`, `decide_staff` |
| `apps/api/app/service.py` | The only code that changes tables, alerts, waitlist | `apply_camera_observation`, `staff_command`, `heartbeat`, `sweep` |
| `apps/api/app/main.py` | HTTP routes, authentication, tenant scoping | `member()`, `_authorize()` |
| `apps/api/app/models.py` | Database tables | |
| `apps/api/app/scenario.py`, `demo.py`, `seed.py` | Scenario replay, per-viewer demo sandboxes, synthetic seed data | |
| `apps/api/app/analytics.py` | Occupancy, turnover, clearing time, peak hours | |
| `apps/worker/worker/zones.py` | Geometry: person box → table | |
| `apps/worker/worker/occupancy_filter.py` | Temporal filter: noisy frames → stable occupied/vacant | module docstring |
| `apps/worker/worker/pipeline.py` | Boxes in, contract-valid events out | |
| `apps/worker/worker/evaluate.py`, `synth.py` | Evaluation metrics; synthetic traces with ground truth | |
| `apps/worker/worker/agent.py`, `transport.py`, `detector.py` | Edge agent, durable queue, detector interface | |
| `apps/web/src/` | React dashboard (`Dashboard.tsx`), setup (`Setup.tsx`), analytics | `App.tsx` → `useFloor` |
| `fixtures/scenarios/*.jsonl` | Scripted scenarios with expectations; shared by tests, demo and simulator | `dinner_basic.jsonl` |
| `fixtures/seed/demo_restaurant.json` | Synthetic restaurant: 12 tables, 3 users, 5 waiting parties | |
| `e2e/golden.cjs` | Browser acceptance test | |
| `eval/manifest.json`, `eval/report.md` | Evaluation sessions and the latest report | |

## 4. Rules that must not be broken

These are the invariants of the product. Every one has a test; if a change makes one of
these tests fail, the change is wrong, not the test.

1. **The camera can cause only two transitions:** Ready → Occupied and Occupied → Needs
   clearing. **Only a person can make a table Ready.** (`test_camera_can_never_produce_ready`)
2. **A staff correction is never overwritten by the camera** until the camera has agreed
   with it (section 5.4). (`test_worked_example_missed_party`, `edge_manual_override.jsonl`)
3. **Every tenant-owned query is scoped by `restaurant_id`**, and a user without a
   membership gets 404. New routes must live under `/v1/restaurants/{rid}/...` and use
   `Depends(member(...))`; otherwise `test_every_route_is_classified` fails on purpose.
4. **No image, track ID or personal attribute enters the system.** Event schemas reject
   unknown fields at the worker, in the JSON Schema and in the API model.
5. **Camera events are idempotent and order-safe** (section 5.5).
6. **Staff can run the floor with no camera:** every transition has a manual command, and
   there is a per-restaurant automation switch.
7. **At most one unresolved alert per table and type** (database unique partial index).
8. **`state_machine.py` stays pure** (no I/O, no clock). All time comes in as arguments so
   tests can control it.

## 5. Core algorithms and logic

This section is the basis of the product. Each part names the file, the rule, the reason,
and the tests.

### 5.1 Person → table (geometry) — `worker/zones.py`

- Each table has one or more **seat polygons** in the camera image, in coordinates
  normalised to 0..1 (they survive a resolution change).
- Each detected person box is reduced to one **anchor point**: horizontally centred, 75%
  of the way down the box. For a seated person that is near the hips, which stays inside
  the seat zone even when head and shoulders overlap a neighbouring table in the image. The
  bottom edge is worse because the table hides the legs.
- **Point-in-polygon by ray casting:** count the polygon edges crossed by a horizontal ray
  from the point; odd means inside. Works for concave zones (L-shaped booths).
- Boxes below the confidence floor (0.35) are dropped. A person counts for one table only.
- Output per frame: people count per table. Presence = count > 0.

### 5.2 Noisy frames → stable occupancy (temporal filter) — `worker/occupancy_filter.py`

Per table, keep a sliding window of `(time, present)` samples (about 2 per second) and
apply **hysteresis with two different windows**:

| Change | Rule | Default |
|---|---|---|
| vacant → occupied | presence in at least `enter_ratio` of the samples of the last `enter_window_s` | 70% of 20 s |
| occupied → vacant | presence in at most `exit_ratio` of the samples of the last `exit_window_s` | 10% of 75 s |

No decision is made until the window is at least 90% full of samples.

Why this shape:

- Someone **walking through** a zone is present for a few samples, far below 70% of 20 s.
- A guest **standing briefly**, a **missed detection** or a short **occlusion** is a gap
  shorter than 75 s, so the table stays occupied.
- The exit rule tolerates 10% stray positives, so one passer-by does **not restart the
  vacancy clock** (a plain "nobody seen for 75 s" rule would).
- Different thresholds each way mean a table cannot flicker.

The trade-off, stated plainly: a departure is reported about 67–75 s after it happens.
Shortening `exit_window_s` gives faster alerts and more false "needs clearing" alerts.
Thresholds are per camera (`cameras.thresholds`, delivered by `/v1/worker/config`).

Known limits of this filter (measured in `eval/report.md`, not hidden):

- A **solo diner who leaves the table for more than 75 s** triggers a clearing alert.
  Staff tap "Still occupied".
- **Staff working at a Ready table for about 14 s or more** can trigger Occupied.
- If **staff start clearing within 75 s of a departure**, the camera never sees an empty
  table in time; staff simply tap "Mark ready" from Occupied.

### 5.3 Table state machine — `api/app/state_machine.py`, contract in `transitions.yaml`

Camera observation, table **not** held:

| State | Camera says | Result |
|---|---|---|
| Ready | occupied | → **Occupied** |
| Occupied | vacant | → **Needs clearing** (opens one alert) |
| anything else | | no change, stored as `ignored_state` |

Needs clearing never changes from a camera event, because staff clearing a table look like
guests. If the camera sees presence there for 3 minutes the card shows "Guests seated?"
with a one-tap confirm.

Staff commands: `mark_ready`, `mark_occupied`, `mark_needs_clearing` (any state → target),
`resume_camera`, `mark_greeted`. A command whose target equals the current state is a
no-op that returns success and writes no event.

Guards, checked first and in this order: automation off → camera offline → observation
older than 120 s → observation older than the last one applied to this table → observation
not newer than the last staff action.

Side effects on entering a state: Occupied resolves the clearing alert; Needs clearing
opens it; Ready resolves all alerts, clears the seated party and recomputes suggestions.

### 5.4 The manual-hold rule (when may the camera act after a correction?)

One rule covers every case:

1. Every staff action sets `manual_hold = true` on that table.
2. While held, camera observations are stored but **never change state**.
3. The hold is released when the camera reports occupancy that **agrees** with the current
   state (occupied for Occupied; vacant for Ready or Needs clearing), observed **after**
   the staff action.
4. After release, the next camera change applies normally.

Worked example: the camera misses a party, staff mark the table Occupied. Camera still says
vacant → ignored. Two minutes later it sees the party → agrees → hold released. An hour
later it reports vacant → Needs clearing.

The same rule handles outages: when a camera comes back online, **all its tables are put on
hold first**, so a reconnect never flips a table by itself; the next heartbeat snapshot
releases the hold on each table where camera and floor agree. Held tables show a "Manual"
badge; "Resume camera" releases a hold by hand.

### 5.5 Ingest: idempotent, order-safe, concurrency-safe — `service.apply_camera_observation`

| Problem | Mechanism |
|---|---|
| Same event delivered twice | `event_id` is unique per restaurant (database index). The repeat returns `duplicate` and changes nothing |
| Events arrive out of order | An observation older than `tables.last_camera_observed_at` is `ignored_stale` |
| Events queued during an outage | Anything observed more than 120 s ago is kept as history and not applied; the heartbeat snapshot restores sync |
| A lost event | Every heartbeat (15 s) carries the occupancy of every zone; each entry is applied as an observation, so the floor self-heals |
| Device clock ahead | `observed_at` is clamped to server time so it cannot block later events |
| Staff and camera write the same table at once | **Optimistic concurrency:** `UPDATE tables ... WHERE id = ? AND version = ?`. The camera path re-reads and decides again (up to 4 times) |
| Two staff tap the same table | Client sends `expected_version`. Stale version + different target → HTTP 409 with the fresh table and who changed it. Same target → success, no duplicate event |

`version` increases only when state or hold changes, so heartbeats never cause spurious
conflicts for staff. Every ignored camera event is stored with its reason, which makes
"why did the table not change?" answerable from the table's history.

Result strings: `applied`, `duplicate`, `hold_released`, `ignored_state`, `ignored_stale`,
`ignored_manual_hold`, `ignored_camera_offline`, `ignored_automation_off`, `rejected`.

### 5.6 Camera health — `service.heartbeat`, `service.sweep`

No heartbeat for 45 s → camera `offline` → dashboard banner, camera events ignored, manual
controls unaffected. Heartbeats also carry `health` (`ok` / `degraded` with a reason: too
dark, overexposed, no detail), computed from simple image statistics on the edge box.

### 5.7 Live updates — `api/app/bus.py`, `web/src/App.tsx` (`useFloor`)

After each committed change the API publishes a small Server-Sent Event. The browser does
not patch local state from events: **on every event, and on every reconnect, it refetches
the whole floor snapshot.** That makes missed or reordered stream messages harmless. A
20-second poll is the last safety net. Timers use the server clock (`server_time` minus the
device clock) so a tablet with a wrong clock still shows correct durations.

The fan-out is in-process, so the API must run as **one process**. To scale out, replace
`bus.publish` with PostgreSQL `NOTIFY` and have each instance `LISTEN`.

### 5.8 Alerts — `service._open_alert`, `service.sweep`

Entering Needs clearing opens one alert; a unique partial index on `(table_id, type)
WHERE status != 'resolved'` makes a second one impossible even under a race. Acknowledging
records who is on it. Marking Ready resolves it. An alert unacknowledged for 5 minutes is
re-notified **once**, as an update to the same row.

### 5.9 Seating suggestion — `service.suggest_seating`

Take Ready tables **smallest first**; give each the party that has **waited longest** among
those that fit (`min_party ≤ party_size ≤ capacity`) and are not already matched. Small
tables first so a couple is not sent to a six-top while a two-top is free. Nothing is
seated automatically: the host confirms, and seating changes the table and the party in
one transaction (a stale tap seats nobody).

### 5.10 Tenant isolation — `main.member`, `main._authorize`

Every `/v1/restaurants/{rid}` route resolves the signed-in user's membership for `rid`;
no membership → 404 (not 403, so IDs are not confirmed to exist). Child objects are always
loaded with `WHERE id = ? AND restaurant_id = ?`. Edge routes take the restaurant from the
device token and reject table IDs of other restaurants. `tests/test_tenancy.py` walks
**every route in the OpenAPI document** with another restaurant's credentials, for all three
roles, and expects 404. Session and device tokens are stored only as SHA-256 hashes;
passwords use scrypt.

### 5.11 Demo sandboxes — `api/app/demo.py`

"Start demo" creates a new restaurant from the seed fixture and signs the visitor in to
it. A sandbox is an ordinary tenant, so isolation between viewers is the same mechanism as
between restaurants. "Reset" deletes and re-seeds that one sandbox under the same ID.
Sandboxes expire after 24 hours. Scenario replay goes through the same service functions
as real camera events.

### 5.12 Analytics — `api/app/analytics.py`

Computed from the append-only `table_events`: a *turn* is one occupied interval;
*clearing time* is Needs clearing → Ready; *occupancy %* is occupied table-seconds divided
by tables × elapsed seconds. Peak hours count arrivals by weekday × hour and by shift, in
the restaurant's time zone. A hand-computed fixture pins the numbers
(`tests/test_analytics.py`).

### 5.13 Vision evaluation — `worker/evaluate.py`

Labels are **events, not boxes**: when the first guest sat (`party_seated`), when the last
left (`party_left`), optionally when staff reset the table (`table_ready`). A prediction
matches a label of the same table and kind if it falls from 10 s before to 180 s after it;
each is used once. Reported, overall and per condition tag: missed departures, false
clearing alerts per table-hour, detection delay (median, 90th percentile), and the same for
arrivals. When `table_ready` labels exist, predictions are first replayed through the
state machine so the numbers describe what staff would see. Sessions are assigned to `dev`
or `heldout` per recording session before tuning; thresholds are tuned on `dev` only.

### 5.14 Retention and privacy — `service.sweep`

Waitlist name and phone are erased 24 hours after a party is seated or removed; raw events
older than 365 days are deleted; expired demo sandboxes are deleted; `DELETE
/v1/restaurants/{rid}` removes a restaurant and everything it owns; `GET .../export`
returns its events.

## 6. How to change things safely

1. Read the rule you are touching in section 5 and its tests first.
2. **State machine change:** edit `transitions.yaml` and `state_machine.py` together, add a
   scenario in `fixtures/scenarios/`, run `make test`.
3. **New endpoint:** put it under `/v1/restaurants/{rid}/`, use `Depends(member("role"))`,
   load children with the restaurant filter, run `make openapi`, add the type in
   `apps/web/src/api.ts`.
4. **Event payload change:** change the JSON Schema, the Pydantic model in `main.py` and
   `worker/pipeline.py` in one commit; bump `schema_version` for breaking changes.
5. **Filter threshold change:** run `make cv-eval` before and after, and report both.
6. Before finishing: `make test` and `make e2e` must pass. State in your summary exactly
   which commands you ran and their results. Do not claim something works unless you ran it.
7. Never store or transmit frames, add identity features, or bypass the tenant filter.
8. Use short-lived branches and pull requests into `main`; keep each change small.

## 7. What is verified and what is not

| Area | Status |
|---|---|
| State machine, ingest, commands, alerts, waitlist, camera outage, roles, tenant isolation, retention, analytics | **Verified** by 59 API tests on SQLite |
| Zones, temporal filter, pipeline, evaluation maths, edge agent control flow, store-and-forward | **Verified** by 21 worker tests with synthetic inputs |
| Full demo path in a real browser (10 steps, two simultaneous viewers, tablet size) | **Verified** by `e2e/golden.cjs` |
| Vision accuracy | **Not verified on real footage.** `eval/report.md` uses synthetic traces; it checks the logic, not a detector. On those traces 6 of 8 targets are met; missed departures (12.5%) miss the 10% target because of the "staff clear within 75 s" case |
| `OnnxYoloxDetector`, RTSP capture loop | **Written, never run** (no model weights, camera or footage in this environment) |
| PostgreSQL | **Not run.** The code is written for both databases; only SQLite was exercised |
| `Dockerfile`, `docker-compose.yml`, GitHub Actions workflow | **Written, never executed** |
| Hosted deployment, monitoring, backups | **Not done** |

## 8. Remaining tasks

Ordered by what blocks the next milestone. IDs are for issue titles.

### Before the hosted demo is public

| ID | Task | Done when |
|---|---|---|
| OPS-1 | Build the Docker image, run `docker compose up`, run the API tests against PostgreSQL in CI | Tests green on PostgreSQL; image serves the demo |
| OPS-2 | Push to GitHub, confirm the CI workflow passes, protect `main` | Three CI jobs green on a pull request |
| OPS-3 | Deploy to a managed host with managed PostgreSQL, HTTPS, `COOKIE_SECURE=1`, `GIT_SHA` set | Demo URL passes `BASE_URL=... node e2e/golden.cjs` |
| OPS-4 | Database migrations with Alembic (today the schema is created with `create_all`) | Upgrade and downgrade tested in CI |
| OPS-5 | Publish test and evaluation reports per build and point the footer "Evidence" link at them | Link opens results for the deployed commit |
| CV-1 | Record consented staged clips, run `worker.runner --video ... --save-trace`, label events, replace synthetic sessions in `eval/manifest.json` | `eval/report.md` no longer says "synthetic" |
| CV-2 | Verify `OnnxYoloxDetector` on those clips (choose weights, check their licence) | Boxes look right on 20 sampled frames; throughput recorded |
| WEB-1 | Show the staged clip next to the floor in the demo, synchronised with the scenario | Clip and floor within 2 s at 1× and 4× |
| WEB-2 | Generate `apps/web/src/api.ts` types from `openapi.json`; add component tests | CI fails on type drift |
| SEC-1 | Add PostgreSQL row-level security as a second layer under the application filter | A query without the tenant setting returns no rows |
| SEC-2 | Rate-limit sign-in; security headers; dependency audit in CI | Checklist filed |

### Before the restaurant pilot

| ID | Task | Done when |
|---|---|---|
| EDGE-1 | Run `worker.agent` against a real RTSP camera on the chosen mini PC; 72-hour soak with power and network cuts | Soak report: no crash, no memory growth, clean recovery |
| EDGE-2 | Package the agent (container, start on boot, pinned version, rollback script, remote support access) | A wiped box is online in 30 minutes from the runbook |
| EDGE-3 | Calibration still: admin requests one frame for zone drawing; deletable | Zone editor shows the real camera view |
| CV-3 | On-site recording with consent and signage; site tuning; go/no-go against targets | On-site held-out report filed |
| CV-4 | Reduce the three known filter limits (section 5.2), for example with a short tracker to separate walking staff from seated guests | Measured improvement on held-out data |
| APP-1 | Staff invitations by email and self-service password change (today an admin sets a temporary password) | Invite link flow tested |
| APP-2 | Observer tap-logger page to record ground truth during audited shifts | 40 table-hours logged and scored |
| APP-3 | Tablet hardening: wake lock, installable web app, sound for alerts | 8-hour unattended run |
| OPS-6 | Backups with a restore drill, error tracking, uptime check, alert on heartbeat age | Unplugging the camera pages the on-call person |
| OPS-7 | Runbooks: installation, rollback, incident handling, printed manual-fallback card | Someone who did not write them follows them successfully |
| LEGAL-1 | Written confirmation of the legal basis and signage for video analytics at the pilot site | Filed before any on-site recording |

### Later releases

| ID | Task |
|---|---|
| L-1 | Wait-time ranges from seating history (25th–75th percentile per party size and day part), fallback below 30 samples, accuracy tracking. `quoted_min`, `quoted_max`, `seated_at` already exist |
| L-2 | Guest-facing status page behind an unguessable expiring link |
| L-3 | "Table ready" notifications through a provider adapter, with opt-in |
| L-4 | Reservation import; POS webhooks (first order resolves the Greeted reminder) |
| L-5 | Multi-camera fusion (occupied if any healthy camera says so; vacant when all agree). The schema already links zones to cameras and tables many-to-many |
| L-6 | Multi-location administration. `organizations` already sits above `restaurants` |
| L-7 | Multiple API instances: move the event fan-out to PostgreSQL `LISTEN/NOTIFY` |

Already built from the "additional features" list: Greeted reminders (opt-in in Setup →
Settings) and the peak-hour report by weekday, hour and shift.
