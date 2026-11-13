# Restaurant Table Management Service — Implementation Plan

## Context

A fixed camera watches restaurant tables. The service detects when parties sit down or leave, moves tables through **Ready → Occupied → Needs Clearing → Ready**, alerts staff to clear, and helps the host seat the next suitable party. This plan takes a four-person part-time team from an empty repository to a hosted demo and then a one-restaurant pilot. It is a plan only: nothing is implemented and no GitHub issues or milestones are created.

**Repository state (inspected 2026-11-13).** `https://github.com/ssartayev/restaurant-ai.git` is public and has **no branches, tags or commits** (`git ls-remote` returns zero refs). There are no files or conventions to preserve, so repository setup is part of Stage 0. Not checked: existing GitHub issues, labels, milestones and branch-protection settings, because this session has git read access only, not GitHub API access. The scaffold owner should look at those before creating milestones.

**Working assumptions** (change any of these and the dates move):

| Assumption | Value |
|---|---|
| Team | 4 part-time developers, **12 h/week each = 48 team-hours/week** |
| Roles | **A** Computer vision · **B** Backend and data · **C** Frontend and product workflows · **D** Deployment and quality (also auth, tenancy, scaffold owner) |
| Pilot site | One restaurant, one camera covering 6–12 tables, wired or solid Wi-Fi internet, a tablet at the host stand |
| Footage | The team can stage and record consented clips themselves from week 1 |
| Budget | Roughly $300–650 one-off hardware, under $130/month hosting |

---

## 1. One-page roadmap

| Stage | GitHub milestone | Weeks | Effort | What exists at the end |
|---|---|---|---|---|
| 0 Foundation | `M0 Foundation` | 1–2 | 55–80 h | Runnable starter project, contracts, synthetic fixtures, CI, first labelled clips |
| 1 First end-to-end prototype | `M1 E2E Prototype` | 3–6 | 150–200 h | Simulated and clip-derived detections drive a live dashboard; staff mark Ready; host seats a waiting party |
| 2 Hosted demo | `M2 Hosted Demo` | 7–11 | 210–270 h | Public URL, per-viewer demo sandbox, setup workflow, roles, alerts, history, basic analytics, evidence page |
| 3 Restaurant pilot | `M3 Pilot` | 12–18 build, 19–22 pilot run | 260–340 h build, about 15 h/week support during the run | Live camera through an on-site edge box, manual fallback, onboarding, runbooks, monitoring, pilot report |
| 4 Later releases | `M4 Later` | after pilot | not estimated | Wait-time estimates, guest status page and notifications, reservation and POS integrations, multi-camera and multi-location |

**Delivery estimate:** hosted demo at about **week 11** (range 10–13), pilot go-live at about **week 19** (range 17–22), pilot report at about week 22. Total build effort is 675–890 hours. The ranges include roughly 15% contingency; they do not include waiting time for hardware delivery or restaurant scheduling.

**Feature-to-release map**

| Feature | Release |
|---|---|
| Dashboard with three states and time in state | M1 (grid), M2 (floor-plan view) |
| Occupancy detection on staged recordings | M1 (offline runner), M2 (tuned, evaluated on held-out clips) |
| Manual table controls, override rule | M1 (controls, rule in state machine), M2 (resume-camera, badges), M3 (kill switch, bulk controls) |
| Waitlist, next-party suggestion, host confirms | M1 (minimal), M2 (polish) |
| Restaurant setup: floor plan, table IDs, capacities, zone configuration | M2 |
| Admin workflow, staff accounts, roles, restaurant-scoped access | M1 (seeded login, scoping), M2 (invites, roles, isolation tests) |
| Needs-clearing alert, acknowledgement, duplicate suppression | M2 |
| Camera offline handling | M2 (heartbeat, banner), M3 (hardened on real hardware) |
| Event history and basic analytics | M2 |
| Live camera | M3 |
| Greeted service reminders | M3, first to defer |
| Peak-hour reporting by day and shift | M3, second to defer |
| Wait-time ranges with fallback and accuracy measure | M4 (needs pilot seating history) |
| Guest-facing status page, notifications | M4 |
| Reservation and POS integrations | M4 |
| Multiple cameras and locations | Schema decisions in M0–M1, implementation in M4 |

**If the schedule slips, defer in this order:** (1) peak-hour report, (2) Greeted reminders, (3) drag-and-drop floor-plan editor (keep the grid view and seed positions from JSON), (4) analytics charts (keep three number tiles), (5) staff invite emails (admin creates accounts with a temporary password), (6) alert re-notification. Never deferred: state machine with the manual-override rule, manual operation, tenant isolation, golden-path E2E test, CV evaluation report.

**Two-developer variant.** Combine roles as **Dev 1 = A + D** (vision, edge, CI, deployment) and **Dev 2 = B + C** (API and UI as one full-stack owner). The split keeps the event contract as the only seam between the two people. At 12 h/week each (24 team-hours/week) the same scope takes about twice as long: demo at about week 21, pilot at about week 36. With the six deferrals above applied up front (about 25% less work) and auth kept to seeded accounts until the pilot, the demo lands at about week 16. Two developers at 20 h/week each is nearly equivalent to the four-person schedule.

**Long-lead dependencies and how to keep building while they are pending**

| Dependency | Needed by | Start | Fallback while pending |
|---|---|---|---|
| Consented staged recordings | M1 week 4 | Week 1 | Hand-written synthetic event traces drive everything except CV evaluation; team members record themselves at any table with a phone on a tripod |
| Camera and edge mini PC | M3 week 13 | Order in week 1–2 | MediaMTX looping a staged clip as a fake RTSP stream; a phone RTSP app; worker runs on a laptop |
| Pilot restaurant agreement, mounting permission, network access | M3 week 16 | Start conversations in week 2 | Bench soak test at a team member's home or office with actors |
| On-site footage consent and signage | M3 week 16 | With the agreement | Tune on staged clips; treat on-site numbers as the first pilot deliverable |
| SMS provider, POS and reservation vendor API access | M4 | During the pilot | Adapter interfaces with a fake provider and recorded webhook fixtures |

**Decisions that need team input** (recommendation given for each; none blocks Stage 0 except D1):

| ID | Decision | Recommendation |
|---|---|---|
| D1 | Confirm weekly hours and who takes roles A–D | 12 h/week each; D is scaffold owner |
| D2 | Hosting provider | One managed platform-as-a-service with managed Postgres (Render or Fly.io); pick whichever a teammate already knows |
| D3 | Person-detector licence | Use an Apache-2.0 detector (for example YOLOX exported to ONNX). Ultralytics YOLO models are AGPL-3.0, which matters if the service is ever offered commercially. Verify the licence of the exact weights before adopting them |
| D4 | Build auth or buy it | Build minimal session auth in the API; switch to a managed identity provider only if SSO is requested |
| D5 | Edge hardware | Fanless x86 mini PC (Intel N100 class) running Docker, chosen after the CV-205 benchmark |
| D6 | Remote support access to the edge box | A mesh VPN such as Tailscale, outbound only, with the restaurant's written agreement |
| D7 | Calibration snapshot retention | Keep one still per camera for zone mapping, taken when the room is empty, deletable by the admin |
| D8 | Legal basis and signage for video analytics in the pilot jurisdiction | Get a short written confirmation before any on-site recording; this plan does not assume a jurisdiction |
| D9 | Vacancy threshold default | 75 s; tune on dev clips (trade-off: detection delay against false clearing alerts) |
| D10 | Raw event retention | 12 months, then daily aggregates only |

---

## 2. Architecture

### Recommended stack

| Part | Choice | Why |
|---|---|---|
| Web app | React + TypeScript + Vite, TanStack Query, Tailwind, SVG for floor plan and zone editors | Common skills, fast local loop, static hosting |
| Backend | Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic | Same language as the vision worker, so the event models are shared code; OpenAPI is generated for the frontend |
| Realtime | Server-Sent Events from the API, fed by Postgres `LISTEN/NOTIFY` | One-way push is all the dashboard needs; works through proxies; no extra broker |
| Database | PostgreSQL 16 (managed), row-level security by `restaurant_id` | One store for state, events and analytics at this scale |
| Vision worker | Python, ONNX Runtime (CPU), Apache-licensed person detector, `supervision` (MIT) for polygon zones and tracking, OpenCV for capture | Runs on a laptop, in CI and on a mini PC without a GPU |
| Auth | Email and password, Argon2 hashes, httpOnly session cookie, role per restaurant membership; per-device bearer tokens for edge agents | Small, testable, no vendor dependency |
| Hosting | Managed PaaS: API container, static web, managed Postgres, cron job; GitHub Actions for CI; GitHub Pages for test evidence; Sentry and an uptime check | Minimal operations work |
| Contracts | JSON Schema for events, `transitions.yaml` for the state machine, committed OpenAPI file with a CI drift check, generated TypeScript types | Each workstream builds against a file, not against another person |

### Where video is processed

**Live video is processed on site, on an edge box inside the restaurant.** The camera is a PoE IP camera exposing RTSP on the local network. The edge agent (a Docker container on the mini PC) pulls the RTSP stream, samples about 2 frames per second, runs person detection in memory, and sends only table-level JSON events to the cloud over outbound HTTPS. No frames are written to disk or uploaded in normal operation, no inbound ports are opened on the restaurant network, and the uplink needs only a few kilobytes per minute. If the internet drops, the agent queues events locally; if the agent or camera drops, the dashboard switches the affected tables to manual mode.

For the hosted demo no inference runs in the cloud. The worker is run once, offline, on consented staged clips; its output (a versioned event trace) is replayed through the same ingest path the edge agent uses, next to the staged clip playing in the browser.

### Diagram

```
 RESTAURANT (on site)                                   CLOUD (one region)
┌──────────────────────────────────────────┐   ┌───────────────────────────────────────────────────┐
│ PoE IP camera ──RTSP (LAN only)──┐       │   │  FastAPI service                                  │
│                                  ▼       │   │  ┌────────────┐   ┌──────────────────────────┐    │
│ Edge box (mini PC, Docker)               │   │  │ Ingest API │──▶│ Table state machine      │    │
│  capture → person detector → zones       │   │  │ (device    │   │ idempotency, ordering,   │    │
│  → dwell/hysteresis filter               │   │  │  token)    │   │ manual-hold rule         │    │
│  → occupancy events + heartbeat ─────────┼──HTTPS──▶──────────┘   └───────┬──────────────────┘    │
│  local SQLite queue (store and forward)  │   │                           │ one transaction       │
│  ◀── zone config, thresholds ────────────┼──HTTPS──            ┌─────────▼─────────┐              │
└──────────────────────────────────────────┘   │                 │ PostgreSQL (RLS)  │              │
                                               │                 │ tables, events,   │              │
 Host tablet / staff phones (browser)          │                 │ alerts, waitlist  │              │
┌──────────────────────────────────────────┐   │                 └─────────┬─────────┘              │
│ React dashboard                          │◀──SSE (table, alert, waitlist, camera status) NOTIFY   │
│  floor, alerts, waitlist, setup          │──REST commands (expected_version)──▶ Dashboard API     │
└──────────────────────────────────────────┘   │  Demo scenario runner ──▶ same Ingest path         │
                                               └───────────────────────────────────────────────────┘
 Dev and CI: simulator CLI or offline worker on staged clips ──▶ same Ingest API
```

### How a detection becomes a dashboard update

1. The agent samples a frame and the detector returns person boxes.
2. Each box's anchor point (a configurable point in the lower half of the box) is tested against the seat-zone polygons of each table.
3. A per-table temporal filter decides occupancy: **occupied** after presence in at least 70% of frames over 20 s; **vacant** after no presence for 75 s (D9). Short gaps, brief standing and people walking through never cross a threshold.
4. On a change the agent emits one `occupancy.changed` event with a unique ID and a per-camera sequence number. Every 15 s it sends a heartbeat carrying the current occupancy of every zone.
5. The ingest API authenticates the device token, validates the schema, drops duplicates by `event_id`, and locks the table row.
6. The state machine applies the transition table and the manual-hold rule, writes the `table_events` row (including ignored events with a reason), updates `tables.state`, `state_since` and `version`, and creates an alert when the new state is Needs Clearing. All in one transaction.
7. The transaction issues `NOTIFY`; the API pushes `table.updated` (and `alert.created`) over SSE to every dashboard of that restaurant. Target: under 1 s from ingest to screen.
8. When a table becomes Ready the API computes the suggested party and pushes `waitlist.suggestion`.

### Key data entities

| Entity | Key fields | Notes |
|---|---|---|
| `organizations` | id, name | Present from day one with a single row per restaurant group; enables multi-location later |
| `restaurants` | id, organization_id, name, timezone, settings, automation_enabled, is_demo, expires_at | Tenant boundary |
| `users`, `memberships` | user id, email, password hash; restaurant_id, role (`admin`, `host`, `staff`) | Role is per restaurant |
| `tables` | id, restaurant_id, label, capacity, min_party, x, y, shape, state, state_since, version, manual_hold, greeted_at, current_party_id | `version` gives optimistic concurrency |
| `cameras` | id, restaurant_id, name, device_token_hash, last_heartbeat_at, status, config_version | One row per camera, many per restaurant allowed |
| `zones` | id, camera_id, table_id, polygons (normalised 0–1), thresholds | A table may have zones on several cameras |
| `table_events` | id, restaurant_id, table_id, source (`camera`, `staff`, `system`), type, from_state, to_state, applied, ignore_reason, actor_user_id, camera_event_id (unique), observed_at, received_at | Append-only; source of history and analytics |
| `alerts` | id, table_id, type (`needs_clearing`, `greet_reminder`), status (`open`, `acknowledged`, `resolved`), acknowledged_by, timestamps | Unique partial index: one open alert per table and type |
| `waitlist_parties` | id, restaurant_id, name, party_size, phone (optional), arrived_at, status (`waiting`, `notified`, `seated`, `cancelled`, `no_show`), seated_table_id, seated_at, quoted_min, quoted_max | Name and phone scrubbed after the retention window |
| `audit_log` | actor, action, target, at | Admin and support actions |

All IDs are prefixed ULIDs (`rst_`, `tbl_`, `cam_`), globally unique. All timestamps are stored in UTC; the restaurant timezone is used only for display and shift bucketing.

### Estimated costs (assumptions; verify current prices before buying)

| Item | Demo | Pilot | Assumption |
|---|---|---|---|
| API container (always on, smallest paid size) | $7–25/mo | $7–25/mo | One instance is enough for tens of dashboards |
| Managed Postgres | $7–20/mo | $20–50/mo | Pilot tier includes point-in-time recovery |
| Staging environment | — | $15–30/mo | Small API plus small database |
| Static web, CI, evidence page, error tracking, uptime check | $0 | $0 | Free tiers; public repository |
| Object storage for staged clips, domain | $2–6/mo | $2–6/mo | Under 50 GB of clips |
| **Monthly total** | **about $20–50** | **about $60–130** | |
| PoE IP camera with RTSP, 1080p or better, good low-light | — | $60–150 once | One camera covers the pilot tables |
| Mini PC (N100 class, 8–16 GB RAM) | — | $180–350 once | CPU inference at 2 fps for 1–3 cameras; validated by CV-205 |
| PoE injector, cable, mount, optional small UPS | — | $40–160 once | |
| **Hardware total** | — | **about $280–660 once** | Host tablet supplied by the restaurant |

---

## 3. Stages: entry, deliverables, exit, parallel work

### Stage summary

| Stage | Entry condition | Deliverables | Exit criteria |
|---|---|---|---|
| **0 Foundation** | Roles and hours confirmed (D1); scaffold owner named | Monorepo scaffold, `make dev`, CI, conventions, contracts v1 (state machine, event schema, OpenAPI stubs), synthetic fixtures, mock server, workflow map, acceptance scenarios, footage plan, first labelled clips, hardware ordered | A second teammate gets the app running from a fresh clone in under 15 minutes; CI is required on `main`; all four have approved contracts v1; fixtures validate in CI |
| **1 E2E prototype** | Stage 0 exit met | State machine, ingest, floor and command APIs, SSE, simulator, seeded login, dashboard grid, manual controls, minimal waitlist with suggestion and seat confirmation, offline vision runner, eval harness v0, golden-path E2E, auto-deployed staging | Golden-path scenario passes in CI and on staging; events produced by the vision runner from a staged clip drive the dashboard to the expected final states; state-machine tests cover every row of `transitions.yaml` |
| **2 Hosted demo** | M1 exit met; at least 60 minutes of labelled staged footage with a locked held-out split | Setup workflow, floor-plan and zone editors, invites and roles, tenant isolation with RLS, alerts, camera health, history, analytics, demo sandbox with scenario runner and reset, production environment, evidence page, demo script | Demo acceptance criteria in §7 all pass; CV targets met on held-out staged clips or gaps documented with a plan |
| **3 Pilot** | M2 exit met; restaurant agreement signed; hardware on the bench; D8 answered | Edge agent with RTSP, store and forward, packaging; device provisioning; kill switch; retention and deletion jobs; onboarding; camera setup page; manual-mode UX; Greeted reminders; peak-hour report; backups, monitoring, runbooks; on-site calibration and evaluation; installation and training | Pilot launch checklist in §11 complete; 72-hour bench soak passed; fallback drill passed on site; pilot success criteria measured and reported after the run |
| **4 Later** | Pilot report reviewed; go/no-go on continuing | Wait-time estimates, guest status page, notifications, reservation and POS adapters, multi-camera fusion, multi-location admin, edge fleet updates | Defined per feature when scheduled |

### Stage-by-stage parallel work

| Stage | A — Computer vision | B — Backend and data | C — Frontend and workflows | D — Deployment and quality | Integrated at |
|---|---|---|---|---|---|
| 0 | S0-10 footage plan and consent; S0-11 record and label first batch | S0-04 state contract; S0-05 event schema; S0-06 OpenAPI stubs; S0-07 fixtures | S0-08 workflow map and wireframes; S0-09 mock server; S0-12 acceptance scenarios | **S0-01 scaffold (merges first)**; S0-02 CI; S0-03 conventions; S0-13 procurement | IC0, end of week 2 |
| 1 | CV-101 detector; CV-102 zones; CV-103 temporal filter; CV-104 offline runner; CV-105 eval harness | BE-101 schema; BE-102 state machine; BE-103 ingest; BE-104 floor and commands; BE-105 SSE; BE-108 waitlist | FE-101 shell; FE-102 grid; FE-103 actions; FE-104 waitlist panel; FE-105 switch to real API | DQ-105 simulator; DQ-106 seeded auth and scoping; DQ-101 integration job; DQ-102 golden E2E; DQ-103 staging | IC1 end of week 4; IC2 end of week 6 |
| 2 | CV-201 second batch and held-out lock; CV-202 tuning and report; CV-203 demo traces; CV-204 config pull and heartbeat; CV-205 RTSP spike; FE-203 zone editor (with C reviewing) | BE-201 alerts; BE-202 admin CRUD and worker config; BE-204 demo sandbox; BE-205 history; BE-206 analytics; BE-207 override hardening; BE-208 camera health | FE-201 setup wizard; FE-202 floor-plan editor; FE-204 alerts UI; FE-205 staff management; FE-206 demo controls; FE-207 history and analytics; FE-208 offline banner and polish | DQ-201 invites and roles; DQ-202 RLS and cross-tenant suite; DQ-203 production; DQ-204 E2E expansion; DQ-205 evidence page; DQ-206 monitoring; DQ-207 demo script | IC3 end of week 9; IC4 end of week 11 |
| 3 | CV-301 RTSP agent; CV-302 queue; CV-303 packaging; CV-304 health signals; CV-305 on-site calibration; CV-306 site tuning; CV-307 audit analysis | BE-301 device provisioning; BE-302 kill switch and audit; BE-303 Greeted; BE-304 retention and deletion; BE-305 peak-hour; BE-306 re-notify; BE-307 audit endpoints; BE-308 snapshot | FE-301 onboarding; FE-302 camera setup; FE-303 manual-mode UX; FE-304 Greeted UI; FE-305 heatmap; FE-306 tablet hardening; FE-307 tap logger | DQ-301 backups; DQ-302 alerting; DQ-303 runbooks; DQ-304 kit and soak; DQ-305 security review; DQ-306 site survey, install, training; DQ-307 pilot report; DQ-308 soak test; DQ-309 remote support | IC5 week 14; IC6 week 16; IC7 week 18 |

### Critical path and concurrency

**Critical path:** S0-01 scaffold → S0-04/05 contracts → BE-102 state machine → BE-103 ingest → BE-104/105 floor API and SSE → FE-105 real-API dashboard → DQ-102 golden E2E → BE-204 demo sandbox → DQ-203 production → demo. For the pilot it continues: CV-205 spike → CV-301/302/303 edge agent → DQ-304 bench soak → DQ-306 installation → CV-305/306 on-site evaluation → go-live. **B is the bottleneck in M1** (about 52 h against 48 h of capacity), which is why D takes the simulator and auth; **hardware and the restaurant agreement are the bottleneck in M3**, which is why they start in week 1–2.

**Concurrency:** after contracts v1 merge, the three build streams do not wait for each other. C builds against the mock server, B builds against the simulator, A builds against clips and labels with no API at all. D builds the test and deployment rails underneath all three. The only hard joins are the integration checkpoints.

**Integration checkpoints** (each ends with the golden-path E2E green on `main` and staging updated):

| ID | When | What must work together |
|---|---|---|
| IC0 | End of week 2 | Everyone runs `make dev` from a fresh clone; contracts v1 approved |
| IC1 | End of week 4 | Walking skeleton: simulator → ingest → state machine → SSE → real dashboard, mocks off |
| IC2 | End of week 6 | M1 review: vision-generated events from a staged clip drive the same path; waitlist seat flow works |
| IC3 | End of week 9 | Demo sandbox on staging; two viewers run and reset independently |
| IC4 | End of week 11 | Demo rehearsal on production with the script; evidence page live |
| IC5 | Week 14 | Edge container on a laptop reads fake RTSP and feeds staging; outage and recovery behave as specified |
| IC6 | Week 16 | Real camera and mini PC on the bench; 72-hour soak started |
| IC7 | Week 18 | Off-hours installation dry run at the restaurant; fallback drill; go/no-go |

A standing rule between checkpoints: `main` always deploys to staging, the golden-path E2E is a required check, and incomplete features merge behind a flag in `restaurants.settings` instead of living on long branches.

---

## 4. Interfaces agreed in Stage 0

### Table states and transitions (`packages/contracts/transitions.yaml`)

| Current state | Trigger | Source | New state | Side effects |
|---|---|---|---|---|
| Ready | occupied | camera | Occupied | Start turn; start Greeted timer (M3) |
| Ready | Seat party / Mark occupied | staff | Occupied | Link party if given; set manual hold |
| Occupied | vacant (sustained) | camera | Needs Clearing | Open clearing alert (deduplicated) |
| Occupied | Party left | staff | Needs Clearing | Open clearing alert; set manual hold |
| Needs Clearing | Mark Ready | staff | Ready | Resolve alert; compute seating suggestion; set manual hold |
| Needs Clearing | occupied or vacant | camera | Needs Clearing (no change) | Recorded as ignored. Staff clearing a table look like guests, so the camera can never leave this state. After 3 minutes of sustained presence the card shows a "Guests seated?" hint with a one-tap confirm |
| Ready | vacant | camera | no change | Releases manual hold if one is set |
| Occupied | occupied | camera | no change | Releases manual hold if one is set |
| any | Correct state (with reason) | staff | chosen state | Set manual hold; audit entry |
| any | any | camera, while camera offline, automation off, or event stale | no change | Recorded as ignored with reason |

The camera can produce only Ready → Occupied and Occupied → Needs Clearing. **Only a person can make a table Ready.**

**Manual-override rule (one rule for every case).** Every staff action sets `manual_hold` on that table. While the hold is set, camera events for that table are recorded but not applied. The hold is released when the camera reports occupancy that *agrees* with the current state (occupied for Occupied, vacant for Ready) with an `observed_at` later than the staff action. After release, the next camera change applies normally. Camera events observed before the latest staff action are always discarded. A held table shows a small "Manual" badge; staff can tap "Resume camera" to release the hold. The same rule applies when a camera comes back from an outage: all its tables start held, so a reconnect never flips a table by itself.

Worked example: the camera misses a party and staff mark the table Occupied. The camera still says vacant: ignored. Two minutes later it sees the party: agrees, hold released. An hour later it reports vacant: Needs Clearing.

### Occupancy event (`packages/contracts/events/occupancy-changed.v1.schema.json`)

```json
{
  "schema_version": 1,
  "event_id": "evt_01JCMZ8Q4T7W2K9XN5B3RHV6YD",
  "type": "occupancy.changed",
  "restaurant_id": "rst_demo",
  "camera_id": "cam_01",
  "table_id": "tbl_07",
  "occupied": false,
  "person_count": 0,
  "confidence": 0.93,
  "observed_at": "2026-11-13T19:42:10.250Z",
  "window_s": 75,
  "sequence": 1842,
  "worker_version": "0.3.1",
  "config_version": 12
}
```

`additionalProperties` is false: there is no field that can carry an image, a track ID or anything about an individual. `observed_at` is when the change became true on camera, not when it was sent. The heartbeat (`camera.heartbeat`, every 15 s) carries `camera_id`, `sequence`, `sent_at`, `health` (`ok`, `degraded`, with a reason) and a `zones` array of `{table_id, occupied, since}`. The ingest response returns one result per event: `applied`, `duplicate`, `ignored_stale`, `ignored_manual_hold`, `ignored_state`, or `rejected`.

### Dashboard API contracts (v1, all under `/v1`, all tenant-scoped)

| Purpose | Endpoint | Notes |
|---|---|---|
| Session | `POST /auth/login`, `POST /auth/logout`, `GET /me` | `/me` returns memberships and roles |
| Floor snapshot | `GET /restaurants/{rid}/floor` | Tables with `state`, `state_since`, `version`, `manual_hold`, camera status, open alerts, server time |
| Table command | `POST /restaurants/{rid}/tables/{tid}/commands` | Body `{command, expected_version, reason?}`; commands `mark_ready`, `mark_occupied`, `mark_needs_clearing`, `resume_camera`, `mark_greeted`. Returns 409 with the current table when `expected_version` is stale; returns 200 with no change when the table is already in the target state |
| Live stream | `GET /restaurants/{rid}/stream` (SSE) | Events `table.updated`, `alert.created`, `alert.updated`, `waitlist.updated`, `waitlist.suggestion`, `camera.status`. On reconnect the client refetches the floor snapshot |
| Alerts | `GET /restaurants/{rid}/alerts?status=open`, `POST /alerts/{id}/ack` | |
| Waitlist | `GET` and `POST /restaurants/{rid}/waitlist`, `PATCH /waitlist/{pid}`, `GET /tables/{tid}/suggestion`, `POST /tables/{tid}/seat` | Seat body `{party_id, expected_version}`; table and party change in one transaction |
| History and analytics | `GET /tables/{tid}/events`, `GET /restaurants/{rid}/analytics/summary?from&to` | |
| Setup | CRUD for tables, cameras, zones, members and invites under `/restaurants/{rid}/…` | Admin role |
| Edge | `POST /ingest/events`, `POST /ingest/heartbeat`, `GET /worker/config` | Device token; the token determines restaurant and camera |
| Demo | `POST /demo/sessions`, `POST /demo/sessions/{id}/scenario/{start,pause,reset}` | Creates and controls a private sandbox |

**Seating suggestion rule (M1):** among waiting parties with `party_size ≤ capacity` (and `≥ min_party` when the table sets one), suggest the one that arrived first. The host always confirms; nothing is seated automatically.

### Test fixtures (`fixtures/`)

| Fixture | Content | Used by |
|---|---|---|
| `seed/demo_restaurant.json` | 12 tables with capacities and positions, one camera, zones, three users (admin, host, staff), five waiting parties | API seed, mock server, demo template |
| `scenarios/dinner_basic.jsonl` | Timed events and staff actions for the golden path, with expected state after each step | Simulator, integration tests, E2E, demo |
| `scenarios/edge_*.jsonl` | Duplicate event, out-of-order event, brief stand, staff walk-through, occlusion gap, camera outage and recovery, manual override then camera disagreement, two staff updating one table | State-machine and ingest tests |
| `clips/tiny_10s.mp4` plus zones and labels | One short consented clip small enough for git | Worker smoke test in CI |
| `eval/manifest.json`, `eval/labels/*.json` | Clip list with checksums, split, and ground-truth `party_seated` and `party_left` times per table | CV evaluation; clips themselves live in object storage |

### How each stream starts without the others

- **Frontend starts with mock data.** `make web-mock` runs the app against a Mock Service Worker layer generated from the OpenAPI file and the seed fixture, including a fake SSE stream that plays `dinner_basic.jsonl`. C builds every screen in M1 before the real API exists. FE-105 turns the mocks off; the mocks stay for component tests.
- **Backend starts with simulated detections.** `make simulate SCENARIO=dinner_basic SPEED=20` posts fixture events to the ingest API. With `--assert` it checks the expected state after each step, which is the integration test. B never needs video.
- **The vision worker is evaluated independently.** `make cv-eval` runs clips plus zone files through the worker and compares emitted events with labels. It needs no API and no database. The worker's only obligation to the rest of the system is to emit schema-valid events.

Contract changes after Stage 0 go through a PR that touches the schema, fixtures and generated types together, with approval from the owners of both sides (enforced by CODEOWNERS on `packages/contracts/`).

---

## 5. Reliability and privacy

### Failure cases and how they are handled

| Case | Handling | Verified by |
|---|---|---|
| Guests briefly standing (coat, photo, restroom with others still seated) | Vacancy needs 75 s with nobody in any seat zone of the table; one remaining guest keeps it occupied | Filter unit tests; `edge_brief_stand` scenario; eval clips |
| A solo diner leaves the table for several minutes | Known limitation: the table will go to Needs Clearing. Staff tap "Still occupied", which sets the hold. Counted as a false clearing alert and reported | Eval metric; pilot correction log |
| Staff walking through or standing at a zone | Occupancy needs presence in 70% of frames over 20 s; transient tracks are ignored. Presence at an already Occupied table is a no-op; presence at a Needs Clearing table never changes state. A staff member working at a Ready table for over 20 s can cause a false Occupied; measured as false occupancy per table-hour and corrected with one tap | Filter unit tests; `edge_walk_through`; eval clips with staff actors |
| Occlusion | Camera mounted high and angled down; the vacancy window bridges short occlusions; zones drawn around seats rather than table tops | Eval clips with occlusion; site survey checklist |
| Lighting changes | Evaluation clips recorded in daylight, evening and dimmed light; the agent reports `degraded` when brightness or mean detection confidence drops below a floor, and the dashboard shows a warning | Eval broken down by lighting; CV-304 tests |
| Camera or edge box outage | No heartbeat for 45 s marks the camera offline: banner on every dashboard, affected tables show "Manual", no camera transitions apply. On recovery all tables are held until the camera agrees with the current state | Integration test with a fake clock; E2E outage scenario; on-site unplug drill |
| Internet outage at the restaurant | Agent queues events in SQLite. On reconnect, events older than 2 minutes are sent as history only and not applied; the next heartbeat snapshot plus the hold rule restores sync. Dashboards on the same failed connection show "Reconnecting" and staff use the printed fallback card | CV-302 tests; soak test with network cuts |
| Duplicate events | `camera_event_id` is unique; a repeat returns `duplicate` and changes nothing | Ingest integration test |
| Out-of-order events | An event whose `observed_at` is older than the table's last applied camera observation, or whose sequence is behind, is stored as `ignored_stale` | Ingest integration test |
| Manual overrides | Hold rule in §4; every staff action is in the audit trail with the actor | State-machine unit tests; `edge_manual_override` |
| Two staff update the same table | Row lock plus `expected_version`. The second request gets 409 and the UI shows "Already marked Ready by Dana" with the fresh state. If both asked for the same target state, the second gets 200 with no change and no duplicate event | Parallel-request integration test; two-browser E2E |
| Duplicate clearing alerts | One open alert per table enforced by a unique partial index; a re-notification is a field update on the same alert | Integration test; E2E |

Staff can always run the floor without the camera: every transition has a manual control, there is a per-restaurant "Camera automation off" switch, and the dashboard works with zero cameras configured.

### Privacy and data handling

- **Table-level events only.** The system stores that a table became occupied or vacant and when. It does not store who sat there, how they looked, or movement between tables. No facial recognition, no re-identification, no biometric templates; track IDs exist only in the agent's memory and are never sent.
- **Video stays on site and in memory.** The agent does not write frames to disk. The cloud never receives video.
- **Exceptions, both explicit:** (1) one calibration still per camera for zone mapping, taken on an admin's request, ideally with the room empty, deletable at any time (D7); (2) evaluation recordings, only with written consent from the restaurant and visible signage, stored encrypted, accessible to the vision owner and one reviewer, deleted 30 days after the pilot report.

| Data | Retention | Access | Deletion |
|---|---|---|---|
| Table events | 12 months raw, then daily aggregates | Restaurant admins; hosts and staff see the current shift | Nightly retention job; full delete on restaurant offboarding |
| Waitlist name and phone | Scrubbed 24 h after the party is seated, cancelled or marked no-show | Hosts and admins of that restaurant | Nightly scrub; test asserts fields are null after the window |
| Staff accounts | Until deactivated by an admin, then anonymised after 30 days | Restaurant admins | Admin action |
| Calibration still | Until replaced or deleted | Restaurant admins | Admin action; removed with the camera |
| Staged recordings (actors) | Until the project ends or consent is withdrawn | Team only | Manual, logged in the manifest |
| Pilot evaluation recordings | 30 days after the pilot report | Vision owner and one reviewer | Manual, logged |
| Demo sandboxes | 24 hours | The viewer who created it | Hourly cleanup job |
| Logs and error reports | 30 days, no guest names or phone numbers logged | Team | Provider retention setting |

Team support access to a pilot restaurant's data uses a named support account, is written to `audit_log`, and is covered by the pilot agreement. A restaurant can request an export (CSV of events and analytics) and full deletion; the deletion runbook is tested on staging before the pilot.

### Verifying tenant isolation

1. **Database layer:** row-level security on every tenant table keyed on a per-transaction `app.restaurant_id` setting; the API connects as a role that cannot bypass it. A test connects without the setting and asserts zero rows.
2. **API layer:** every route resolves the restaurant from the session membership or device token, never from the request body alone.
3. **Automated cross-tenant suite (DQ-202):** the test seeds restaurants A and B, then walks **every route in the OpenAPI file** using B's credentials against A's IDs and expects 404, for each role and for a device token. A new route without a case fails CI, so coverage cannot silently lapse.
4. **Stream check:** an E2E test opens B's dashboard, triggers changes in A, and asserts B's SSE stream stays silent.
5. **Demo sandboxes** are ordinary restaurants, so the same suite proves one viewer cannot see another's sandbox.

---

## 6. Testing and evidence

### Test layers

| Layer | Scope | Tools | Runs |
|---|---|---|---|
| Unit | State machine (table-driven from `transitions.yaml`), temporal filter, zone geometry, suggestion rule, analytics queries, UI components | pytest, Vitest | Every PR, under 3 minutes |
| Integration | API with real Postgres: ingest idempotency and ordering, commands and 409s, alerts, SSE delivery, heartbeat timeout, retention jobs, cross-tenant suite, scenario replay with `--assert` | pytest, Postgres service container | Every PR |
| Contract | Fixtures validate against JSON Schema; committed OpenAPI matches the code; generated TypeScript types are current | CI drift check | Every PR |
| Browser E2E | Full stack in Docker Compose: golden path, alert acknowledgement, two-user conflict, outage, demo reset isolation, setup workflow | Playwright (desktop and tablet viewport) | Every PR for the golden path; full suite on `main` and nightly |
| CV evaluation | Worker on labelled clips: dev split on PRs that touch the worker, held-out split on `main` and before each milestone | `make cv-eval` | As stated |
| Soak and load | 30 tables, 5 dashboards, 8-hour replay; edge box 72 hours with network cuts | Simulator, bench kit | Before the pilot |

### Repeatable end-to-end scenario (`dinner_basic`)

1. Seed: table T7 (four seats) is Ready; the waitlist holds "Kim, party of 4, arrived 18:50" and "Lee, party of 2, arrived 18:55".
2. Camera reports T7 occupied → card shows **Occupied**, timer starts.
3. Camera reports a brief vacancy shorter than the threshold (represented in the trace by no event) → still Occupied.
4. Camera reports T7 vacant → **Needs Clearing**; exactly one alert appears. A duplicate of the same event is posted → still exactly one alert.
5. Staff user acknowledges the alert → alert shows who acknowledged.
6. Staff user taps Mark Ready → **Ready**; alert resolved; suggestion banner "Seat Kim (4) at T7".
7. Host confirms → T7 **Occupied**, Kim is `seated`, Lee remains first in the list.
8. History for T7 lists every step with source and time; analytics shows one completed turn and a departure-to-Ready time equal to the scripted gap.

The same file drives the integration test, the Playwright test, the simulator and the hosted demo, so the reviewer watches exactly what CI checks.

### CV evaluation method

- **Labels are events, not boxes.** For each clip and table: the time the first guest is seated (`party_seated`) and the time the last guest leaves the zone (`party_left`), plus tags (`lighting`, `occlusion`, `staff_pass`, `brief_stand`, `solo_absence`). Two people label a 20% sample; disagreements over 5 s are reviewed. A validator checks the label files in CI.
- **Hold-out by recording session, not by excerpt.** Sessions are assigned 60% to dev and 40% to held-out before any tuning, stratified by tag. The held-out list and checksums are committed in `eval/manifest.json`; thresholds are tuned on dev only, and the held-out report is generated by CI, not by hand. On-site pilot footage forms a second, separate held-out set.
- **Matching.** A predicted event matches a ground-truth event of the same table and type if it falls between 10 s before and 180 s after it. Each prediction matches at most one label.
- **Reported metrics** (overall and per tag): missed departures (unmatched `party_left` ÷ all `party_left`); false clearing alerts per table-hour (unmatched predicted vacancies while truly occupied ÷ table-hours observed); departure detection delay (median and 90th percentile of predicted minus true time); the same three for arrivals; frames per second and CPU on the reference machine.

| Metric | Demo target (held-out staged clips) | Pilot target (on-site audit) |
|---|---|---|
| Missed departures | ≤ 10% | ≤ 5% |
| False clearing alerts | ≤ 0.2 per table-hour | ≤ 0.1 per table-hour |
| Departure detection delay | median ≤ 90 s, p90 ≤ 150 s | same |
| Missed arrivals | ≤ 5% | ≤ 5% |
| False occupancy | ≤ 0.1 per table-hour | ≤ 0.1 per table-hour |
| Arrival detection delay | median ≤ 30 s, p90 ≤ 60 s | same |

These are starting targets chosen so the system is useful with a 75 s vacancy threshold; they are not yet backed by data and should be revisited after the first held-out report (CV-202). With fewer than about 50 departures in the held-out set the percentages carry wide uncertainty, so the report states counts next to rates.

**Validating in the pilot.** (1) Audited sessions: an observer uses a tap-logger page (FE-307) to record true arrivals and departures for at least three shifts and 40 table-hours; CV-307 scores system events against it with the same matching code. (2) Continuous proxy: every staff correction ("Still occupied", manual Party left, manual Occupied) is counted per table-hour and reviewed weekly. (3) With consent, a recorded calibration shift is labelled and added to the on-site held-out set.

### Requirement-to-test map

| ID | Critical requirement | Tests | Proof artifact |
|---|---|---|---|
| R1 | Departure moves a table to Needs Clearing; only staff make it Ready | State-machine unit tests; `dinner_basic` integration; golden E2E | Unit report; Playwright report |
| R2 | Camera cannot overwrite a manual correction until it agrees | Unit tests for the hold rule; `edge_manual_override` | Unit report |
| R3 | Duplicate and out-of-order events change nothing | Ingest integration tests | Integration report |
| R4 | One clearing alert per departure, acknowledgeable | Alert integration test; E2E | Integration and Playwright reports |
| R5 | Two staff updating one table never corrupt state | Parallel-request test; two-browser E2E | Integration and Playwright reports |
| R6 | A restaurant cannot access another's data | RLS test; cross-tenant suite over all routes; silent-stream E2E | Dedicated "tenant-isolation" CI job |
| R7 | Floor runs manually when the camera is offline | Heartbeat-timeout test; outage E2E; on-site drill | Reports; signed drill checklist |
| R8 | Next eligible party is suggested; host confirms | Suggestion unit tests; golden E2E | Reports |
| R9 | Detection quality meets targets | Held-out evaluation | `cv-eval` report with counts, rates and per-tag breakdown |
| R10 | Demo reset does not affect other viewers | Two-context E2E | Playwright report |
| R11 | No images leave the site; retention enforced | Schema forbids extra fields; agent egress test captures outbound requests and asserts JSON only; retention job tests | Integration report |
| R12 | Analytics numbers are correct | Fixture with hand-computed expected values | Integration report |

**Milestone evidence.** Every `main` build publishes to GitHub Pages: the Playwright HTML report with traces for failures, unit and integration results with coverage, the tenant-isolation job result, and the latest CV evaluation report. M1 passes when R1, R2, R3, R8 are green and IC2 is recorded. M2 passes when R1–R6, R8–R10 and R12 are green on the tagged demo release and the demo script has been run by someone outside the team. M3 launch passes when R7 and R11 are green, the soak report and drill checklist are filed, and the launch checklist is complete; M3 success is the pilot report against §7.

---

## 7. Milestone acceptance criteria

### Hosted demo

1. A reviewer opens the demo URL on a laptop or tablet with no account and no installation, and taps **Start demo**.
2. They land in a private demo restaurant seeded with synthetic data: 12 tables, 5 waiting parties, a few hours of prior history so analytics is not empty. No real guest or staff data is present.
3. They start the staged scenario. The staged clip plays beside the floor and tables change state in step with it, with time in state counting up.
4. When a party leaves, the table shows Needs Clearing within the scripted time and one alert appears. They acknowledge it and mark the table Ready.
5. A suggestion names the next eligible party; they confirm, the table becomes Occupied and the party leaves the waiting list.
6. They can switch between host, staff and admin views, open the setup screens (floor plan, tables, zones) and see history and analytics for their sandbox.
7. They run the "camera offline" scenario and operate tables manually.
8. **Reset** restores the seeded state in under 5 seconds. A second viewer in another browser is unaffected by the first viewer's actions or reset (covered by an automated test).
9. An **Evidence** link opens the latest test and CV evaluation reports for the deployed commit; the page footer shows the commit hash.
10. The full script takes under 10 minutes and works three times in a row.

**How reset isolation works.** *Start demo* clones a read-only template restaurant into a new restaurant row set with a random ID and an anonymous session scoped to it. The scenario runner replays the trace into that sandbox only. *Reset* deletes and re-clones that one sandbox. An hourly job removes sandboxes older than 24 hours. Demo creation is rate-limited per IP.

**Demo script (about 8 minutes)**

1. Open the URL, tap *Start demo*. Point out the three states and the timers.
2. Tap *Play scenario* at 4× speed. Watch a party sit at T7 in the clip and the card turn Occupied.
3. Note a guest standing briefly: the table stays Occupied.
4. The party leaves: T7 turns Needs Clearing and an alert sounds once.
5. Switch to the staff view, acknowledge the alert, tap *Mark Ready*.
6. Switch to the host view: "Seat Kim (4) at T7". Confirm. Show the waitlist update.
7. Add a walk-in party of 2; show which Ready table is suggested.
8. Run *Camera offline*: banner appears, mark a table Occupied by hand, bring the camera back, show the Manual badge clearing.
9. Open T7's history, then the analytics tiles.
10. Open *Evidence*, show green test results and the CV report. Tap *Reset*.

### Restaurant pilot

Launch acceptance (before the first live shift):

1. An admin invites staff; each sets a password and sees only that restaurant. A staff member can be deactivated.
2. The admin maps tables: labels, capacities, floor positions, and seat zones drawn on a calibration still from the live camera.
3. The edge box is installed, shows "Online" on the camera page, and survives a power cycle without manual steps.
4. During an off-hours rehearsal with team members as guests, the golden path works end to end from the live camera.
5. Fallback drill: the camera is unplugged mid-rehearsal; within 60 s the dashboard shows offline; staff complete two table turns manually; the camera is restored and no table flips unexpectedly.
6. Rollback drill: the previous edge image and the previous cloud release are each restored in under 15 minutes on staging and the bench kit.
7. Support path is in place: named on-call person per pilot shift, contact number on the fallback card, monitoring alerts reaching the team.

Pilot success criteria (measured over at least 3 weeks and 10 service shifts):

| Criterion | Target | Source |
|---|---|---|
| Used in service | ≥ 10 shifts with at least 80% of table turns passing through the system | Event data |
| Camera pipeline availability | ≥ 95% of service hours online | Heartbeat data |
| Missed departures | ≤ 5% (stretch) and no worse than 10% | Audited sessions, ≥ 40 table-hours |
| False clearing alerts | ≤ 0.1 per table-hour (stretch) and no worse than 0.2 | Audited sessions and correction log |
| Staff corrections | ≤ 1 per 10 table turns by week 3 | Event data |
| Alert acknowledgement | Median under 2 minutes | Alert data |
| Departure-to-Ready time | Baseline in week 1; report the change by week 3 (hypothesis: 15% shorter) | Event data |
| Fallback | Every outage handled manually with no lost shift; no unresolved severe incident lasting over one shift | Incident log |
| Privacy and isolation | Zero incidents; no stored video outside the consented evaluation set | Audit |
| Staff view | ≥ 70% of surveyed staff and the manager would keep using it | Short survey |

---

## 8. Backlog by milestone

Each row is one GitHub issue. Title format `[ID] Title`; labels `area:cv|backend|frontend|platform`, `type:feature|test|chore|spike`, `deferrable` where noted. Owner is the primary role; every PR needs one review from another role. Estimates are rough hours.

### M0 Foundation

| ID | Task | Owner | Depends on | Definition of done | h |
|---|---|---|---|---|---|
| S0-01 | Monorepo scaffold: `apps/web`, `apps/api`, `apps/worker`, `packages/contracts`, `fixtures`, `eval`, `infra`, `docs`; Makefile; Docker Compose with Postgres; hello page calling `/healthz`; README quick start | D | — | A second teammate goes from fresh clone to the page showing API status in under 15 minutes on their OS and confirms in the PR | 10 |
| S0-02 | CI workflows: lint, type-check, unit tests for web, api, worker; branch protection on `main` | D | S0-01 | A PR with a deliberately failing test cannot be merged; CI under 6 minutes | 5 |
| S0-03 | Conventions: CONTRIBUTING, CODEOWNERS, PR and issue templates, labels, milestone names | D | S0-01 | Templates appear on a new PR and issue; CODEOWNERS requests the right reviewer on a contracts change | 3 |
| S0-04 | State machine contract `transitions.yaml` and written manual-hold rule | B | — | All four approve; a test loads the file and fails on an undefined state or trigger | 4 |
| S0-05 | Event and heartbeat JSON Schemas v1 with examples | B, A reviews | — | Schema test accepts the examples and rejects three invalid payloads, including one with an extra field | 4 |
| S0-06 | OpenAPI v1: stub routes for floor, commands, stream, alerts, waitlist returning fixture data; TypeScript type generation; drift check | B | S0-01 | `make contracts` regenerates with no diff; CI fails when the code and committed OpenAPI differ | 8 |
| S0-07 | Synthetic fixtures: seed restaurant, `dinner_basic`, eight edge scenarios with expected states | B | S0-04, S0-05 | Every fixture validates in CI; expected states reviewed against `transitions.yaml` by D | 6 |
| S0-08 | Workflow map and wireframes for host, floor staff and admin | C | — | Doc in `docs/product/` walked through with the team in 30 minutes; open questions listed as issues | 6 |
| S0-09 | Mock server for the web app from OpenAPI and fixtures, including a fake stream | C | S0-06, S0-07 | `make web-mock` shows the seeded floor and plays `dinner_basic` with the API stopped | 4 |
| S0-10 | Footage plan: shot list, camera height and angle, consent form, storage and manifest format, label format and validator | A | — | Doc merged; consent form approved by the team; first session scheduled | 4 |
| S0-11 | Record and label the first staged batch: at least 6 clips, 40 minutes, two edge cases | A | S0-10 | Clips in storage; manifest with checksums merged; labels pass the validator; signed consent forms filed | 10 |
| S0-12 | Acceptance scenarios in Given/When/Then for the golden path and eight edge cases, mapped to R1–R12 | C | S0-04 | Reviewed by B and D; each scenario names its fixture | 4 |
| S0-13 | Start long-lead items: order camera and mini PC, open pilot-restaurant conversation, raise D8 | D | — | Orders placed or blocked with a named reason; contact logged in `docs/pilot/` | 2 |

### M1 First end-to-end prototype

| ID | Task | Owner | Depends on | Definition of done | h |
|---|---|---|---|---|---|
| BE-101 | Database schema and Alembic baseline for organisations, restaurants, users, memberships, tables, cameras, zones, table_events; seed loader | B | S0-07 | Migration up and down passes in CI; `make seed` loads the demo restaurant | 8 |
| BE-102 | State machine as a pure module implementing `transitions.yaml` and the manual hold | B | S0-04 | Table-driven tests cover every row and every edge scenario; full branch coverage of the module | 10 |
| BE-103 | Ingest endpoint with device token, schema validation, idempotency, ordering, persisted results | B | BE-101, BE-102 | Integration tests return `applied`, `duplicate`, `ignored_stale`, `ignored_manual_hold` in the right cases | 8 |
| BE-104 | Floor snapshot and table command endpoints with `expected_version` | B | BE-102 | Stale version returns 409 with current state; 20 parallel identical commands produce one event | 8 |
| BE-105 | SSE stream backed by `LISTEN/NOTIFY` | B | BE-104 | Test client receives `table.updated` within 1 s of a command; documented reconnect behaviour | 8 |
| BE-108 | Minimal waitlist: add, list, suggestion, seat confirmation | B | BE-104 | Tests for size fit and arrival order; seat changes table and party atomically; a stale version seats nobody | 10 |
| DQ-105 | Simulator CLI replaying scenario files at a chosen speed, with `--assert` | D | S0-07, BE-103 | `make simulate SCENARIO=dinner_basic` drives the local floor; `--assert` exits non-zero on a wrong state | 5 |
| DQ-106 | Seeded-user login, session cookie, restaurant scoping dependency used by every route | D | BE-101 | 401 without a session; a user of restaurant B gets 404 on restaurant A's floor and commands | 8 |
| DQ-101 | Integration CI job with Postgres and scenario replay | D | DQ-105 | Job runs all scenarios with `--assert` on every PR | 5 |
| DQ-102 | Playwright golden-path test against Docker Compose | D | FE-105 | Steps 1–8 of `dinner_basic` pass in CI in under 10 minutes; HTML report uploaded | 10 |
| DQ-103 | Staging environment auto-deployed from `main` | D | S0-02 | URL reachable; `/healthz` returns the commit hash; a merge is live within 10 minutes | 8 |
| DQ-104 | IC1 and IC2 reviews, bug triage, M1 sign-off note | D | all M1 | Checkpoint notes in `docs/checkpoints/` with what was shown and open bugs | 3 |
| FE-101 | App shell: routing, login, generated API client, stream hook with reconnect and refetch | C | S0-09 | Component tests for login and reconnect; works against mocks | 8 |
| FE-102 | Dashboard grid: table cards with state colour, icon and text, capacity, ticking time in state | C | FE-101 | Tests for three states; timer derives from `state_since` and server time; states distinguishable without colour | 10 |
| FE-103 | Table actions with optimistic update and 409 handling | C | FE-102 | Test shows the conflict message and the refreshed state | 6 |
| FE-104 | Waitlist panel: add party, list, suggestion banner, confirm seating | C | FE-101 | Component tests for add, suggest, confirm against mocks | 10 |
| FE-105 | Switch the dashboard to the real API and stream | C | BE-104, BE-105, BE-108, DQ-106 | With mocks off, `make simulate` visibly drives the dashboard locally and on staging | 5 |
| CV-101 | Detector wrapper behind a `Detector` interface, ONNX Runtime, frame sampling | A | S0-01, D3 | Runs on the tiny clip in CI and returns person boxes; throughput on the reference laptop recorded in the README | 8 |
| CV-102 | Zone assignment with normalised polygons and a configurable anchor point; zone file format | A | S0-05 | Unit tests with synthetic boxes inside, outside and on the boundary | 6 |
| CV-103 | Temporal occupancy filter with enter and exit thresholds, emitting schema-valid events | A | CV-102 | Unit tests on synthetic timelines: brief stand, walk-through, occlusion gap, real departure | 10 |
| CV-104 | Offline runner: clip plus zones to `events.jsonl`, optional `--post` to the API | A | CV-101, CV-103 | Output from a staged clip, replayed locally, reaches the expected final states | 5 |
| CV-105 | Evaluation harness v0: match events to labels, write metrics JSON and a Markdown report | A | S0-11, CV-104 | `make cv-eval` reproduces the same numbers twice; matching logic tested on hand-built cases | 10 |

### M2 Hosted demo

| ID | Task | Owner | Depends on | Definition of done | h |
|---|---|---|---|---|---|
| BE-201 | Alerts: open on Needs Clearing, one open per table, acknowledge, resolve on Ready, stream events | B | BE-105 | Duplicate departure yields one alert; acknowledgement records the user; integration tests pass | 8 |
| BE-202 | Setup API: tables, cameras, zones, config versioning, worker config endpoint | B | BE-101 | CRUD tests; changing a zone bumps `config_version`; admin role required | 12 |
| BE-204 | Demo sandbox: clone template, per-sandbox scenario runner with start, pause, reset, 24-hour cleanup, rate limit | B | BE-201, DQ-202 | Two sandboxes run concurrently without cross-effects; reset under 5 s; cleanup test passes | 14 |
| BE-205 | Table event history endpoint with pagination | B | BE-103 | Returns events newest first with source and actor; tenant-scoped | 4 |
| BE-206 | Analytics summary: occupancy percentage, turns, mean turn length, median departure-to-Ready | B | BE-205 | Fixture with hand-computed values matches exactly | 10 |
| BE-207 | Override hardening: `resume_camera`, `manual_hold` in the snapshot, ignore reasons in history, "Guests seated?" hint | B | BE-102 | Unit and integration tests for each path in the worked example | 6 |
| BE-208 | Camera health: heartbeat endpoint, offline after 45 s, held tables on recovery, `camera.status` stream event | B | BE-103 | Fake-clock test for offline and recovery; outage scenario passes with `--assert` | 8 |
| DQ-201 | Invites and roles: invite token, accept, set password, role checks on every route, deactivate | D | DQ-106 | Role matrix test: each role against each route group | 10 |
| DQ-202 | Row-level security and the cross-tenant suite generated from OpenAPI | D | DQ-106, BE-202 | A new route without an isolation case fails CI; RLS test returns zero rows without the tenant setting | 10 |
| DQ-203 | Production demo environment, domain, TLS, secrets, deploy by tag, post-deploy smoke test | D | DQ-103 | Tagging a release deploys it; smoke test runs the golden path against production in a throwaway sandbox | 8 |
| DQ-204 | E2E expansion: demo path, reset isolation with two contexts, alert acknowledgement, two-user conflict, outage, setup | D | BE-204, FE-206 | All pass on `main` at desktop and tablet sizes | 12 |
| DQ-205 | Evidence page: publish Playwright, coverage, isolation and CV reports per `main` build; link from the app footer | D | DQ-102, CV-202 | The Evidence link in the deployed demo opens reports for the deployed commit | 6 |
| DQ-206 | Error tracking, uptime check, structured request logs with restaurant ID and no guest PII | D | DQ-203 | A forced error appears in the tracker; downtime alert reaches the team channel | 5 |
| DQ-207 | Demo script, reviewer guide, rehearsal with an outside person | D | all M2 | Outside reviewer completes the script unaided; notes filed | 4 |
| FE-201 | Setup wizard: restaurant details, tables with label and capacity | C | BE-202 | E2E creates a restaurant with three tables that appear on the dashboard | 8 |
| FE-202 | Floor-plan editor: drag tables on a grid, save; floor view on the dashboard (`deferrable`) | C | FE-201 | Positions persist; dashboard toggles between grid and floor views | 14 |
| FE-203 | Zone editor: draw and edit polygons over a still frame, assign to tables | A, C reviews | BE-202 | Saved polygons round-trip to the worker config; the offline runner produces events with zones drawn in the UI | 14 |
| FE-204 | Alerts UI: toast, list, badge, acknowledge, optional sound | C | BE-201 | Component tests; E2E acknowledgement | 8 |
| FE-205 | Staff management: invite, role, deactivate | C | DQ-201 | E2E invites a user who then logs in with the right role | 6 |
| FE-206 | Demo entry and controls: Start demo, play, pause, speed, reset, role switcher, synchronised staged clip | C | BE-204, CV-203 | Clip and floor stay within 2 s of each other at 1× and 4× | 10 |
| FE-207 | Table history drawer and analytics page with three tiles and one chart | C | BE-205, BE-206 | Values match the API in an E2E check | 12 |
| FE-208 | Offline banner, Manual badges, tablet layout and accessibility pass | C | BE-207, BE-208 | Automated accessibility scan has no serious issues; usable at 768 px width | 8 |
| CV-201 | Second recording batch covering lighting, occlusion, staff pass-through, solo absence; labels; lock the held-out split | A | S0-10 | At least 60 minutes total; manifest locked with checksums; double-labelled sample agreement reported | 12 |
| CV-202 | Tune thresholds on dev; publish evaluation report v1 on held-out with per-tag breakdown | A | CV-105, CV-201 | Report generated by CI; each target marked met or missed with counts | 10 |
| CV-203 | Demo traces: run the worker on the demo clips, commit versioned traces and clip assets | A | CV-202 | The demo scenario uses worker output unedited; any hand edits are listed | 6 |
| CV-204 | Worker pulls zones and thresholds from the API and sends heartbeats with a snapshot | A | BE-202, BE-208 | Changing a zone in the UI changes worker behaviour without a restart | 8 |
| CV-205 | Spike: read fake RTSP from MediaMTX; benchmark frames per second and CPU on candidate hardware | A | CV-101 | One-page result with a hardware recommendation (D5) | 8 |

### M3 Restaurant pilot

| ID | Task | Owner | Depends on | Definition of done | h |
|---|---|---|---|---|---|
| CV-301 | Edge agent: RTSP capture with reconnect and backoff, watchdog, graceful degradation | A | CV-205 | Survives 20 forced stream drops in a test without restart or memory growth | 12 |
| CV-302 | Store-and-forward queue with stale policy, batching, retry | A | CV-301 | Network-cut test: no duplicates applied, stale events marked history-only | 8 |
| CV-303 | Edge packaging: Docker image, Compose file, start on boot, pinned version, provisioning script | A | CV-302, BE-301 | A wiped mini PC is online in under 30 minutes by following the install runbook | 10 |
| CV-304 | Health signals: brightness, blur, confidence floor; optional moved-camera check | A | CV-301 | Covering the lens reports `degraded` within 60 s | 8 |
| CV-305 | On-site calibration recording and labelling with consent | A | D8, DQ-306 | At least one service period labelled as the on-site held-out set | 14 |
| CV-306 | Site tuning and on-site evaluation report; go/no-go against targets | A | CV-305 | Report filed; decision recorded at IC7 | 10 |
| CV-307 | Score audited sessions against system events | A | BE-307 | Weekly numbers produced by one command | 6 |
| BE-301 | Device provisioning: one-time registration code, token rotation and revocation | B | BE-202 | Revoked token is rejected within 60 s; test passes | 6 |
| BE-302 | Automation kill switch per restaurant and per table; audit log of staff and admin actions | B | BE-207 | With automation off, camera events are stored and not applied | 6 |
| BE-303 | Greeted reminders: timer after Occupied, reminder alert, resolve on `mark_greeted` or an external resolver hook (`deferrable`) | B | BE-201 | Fake-clock tests for remind, resolve and no duplicate | 8 |
| BE-304 | Retention and deletion: waitlist PII scrub, event ageing, restaurant export and delete | B | BE-206 | Tests prove scrub after the window and complete removal on delete | 10 |
| BE-305 | Peak-hour report by weekday and shift or hour (`deferrable`) | B | BE-206 | Fixture with hand-computed buckets matches; uses the restaurant timezone | 10 |
| BE-306 | Re-notify once for unacknowledged clearing alerts; per-restaurant alert settings | B | BE-201 | One reminder at the configured delay, never a second alert row | 4 |
| BE-307 | Audit-session endpoints for the tap logger | B | BE-205 | Stored separately from table events; exportable | 4 |
| BE-308 | Calibration still: admin requests, agent uploads one frame, admin can delete | B | BE-301 | Only on explicit request; delete removes the file; access limited to admins | 6 |
| FE-301 | Pilot onboarding: accept invite, set password, role-based navigation, in-app quick start | C | DQ-201 | A new staff member reaches the dashboard in under 3 minutes in a hallway test | 8 |
| FE-302 | Camera setup page: registration code, status, last heartbeat, request still, map zones on it | C | BE-301, BE-308 | Admin completes camera setup without developer help in rehearsal | 10 |
| FE-303 | Manual-mode UX: automation toggle, bulk mark, per-table resume | C | BE-302 | Outage E2E passes using only these controls | 8 |
| FE-304 | Greeted tap and reminder chip (`deferrable`) | C | BE-303 | Component and E2E tests | 5 |
| FE-305 | Peak-hour heatmap (`deferrable`) | C | BE-305 | Matches the API for the fixture | 8 |
| FE-306 | Tablet hardening: screen wake lock, reconnect indicator, large touch targets, installable web app | C | FE-208 | Runs 8 hours on the pilot tablet without sleeping or losing the stream unnoticed | 8 |
| FE-307 | Observer tap-logger page | C | BE-307 | Observer logs arrivals and departures for 12 tables one-handed | 4 |
| DQ-301 | Backups, point-in-time recovery, restore drill | D | DQ-203 | Restore to a scratch database verified; time recorded | 5 |
| DQ-302 | Pilot alerting: heartbeat age, ingest errors, API error rate, to the on-call channel | D | DQ-206 | Unplugging the bench camera pages the on-call within 2 minutes | 8 |
| DQ-303 | Runbooks: installation, rollback (cloud and edge), incident handling, printed manual-fallback card, support contacts | D | CV-303 | A teammate who did not write them performs install and rollback from the text alone | 8 |
| DQ-304 | Assemble the pilot kit; 72-hour bench soak with fake RTSP then the real camera | D | CV-303 | Soak report: no crash, no memory growth, recovery from three power cuts and three network cuts | 10 |
| DQ-305 | Security review: authorisation tests, rate limits, session settings, secret handling, dependency audit | D | DQ-202 | Checklist filed; no open high-severity findings | 8 |
| DQ-306 | Site survey, installation, network check, staff training | D | DQ-304 | Survey form complete; install checklist signed by the manager; training attended by each shift lead | 10 |
| DQ-307 | Pilot report template, weekly review, staff survey | D | — | Weekly one-page report produced from data; final report against §7 | 6 |
| DQ-308 | Load and soak: 30 tables, 5 dashboards, 8-hour replay | D | DQ-203 | No errors; ingest-to-screen p95 under 1 s | 5 |
| DQ-309 | Remote support access to the edge box; update and rollback tested | D | D6, CV-303 | Update then rollback done remotely on the bench kit in under 15 minutes | 5 |

### M4 Later releases (drafted, not estimated)

| ID | Task | Notes and definition of done |
|---|---|---|
| L-401 | Wait-time ranges | Range = 25th to 75th percentile of historical waits for the same party-size bucket and day part. **Fallback** when fewer than 30 comparable samples: parties ahead that fit the same tables × average turn length ÷ matching tables, shown as "rough estimate". **Accuracy:** store every quoted range; report the share of actual waits inside the range (target ≥ 70%) and mean absolute error, per week. `quoted_min`, `quoted_max` and `seated_at` are in the schema from M1 so history accrues during the pilot |
| L-402 | Guest status page | Unguessable expiring link showing position and range only; no names; opt-in per restaurant. Done when a link stops working after seating and reveals nothing about other parties |
| L-403 | Notifications | Provider adapter (SMS, messaging app or email) with a fake for tests; guest opt-in recorded; sent when the host taps Notify. Done when a ready-table message is delivered once and logged |
| L-404 | Reservation integration | Adapter interface; reservations appear as parties with a due time and optional table hold. Done against recorded vendor fixtures before real access |
| L-405 | POS integration | Webhook adapter mapping POS table IDs to tables. First order event calls the Greeted resolver hook from BE-303; a paid-check event shows a "leaving soon" hint and never changes state by itself |
| L-406 | Multi-camera fusion | A table is occupied if any healthy camera says so, vacant only when all healthy cameras covering it agree |
| L-407 | Multi-location administration | Organisation-level admins, location switcher, cross-location reports |
| L-408 | Edge fleet updates | Staged remote updates with automatic rollback on failed health check |
| L-409 | Greeted reminders or peak-hour report | Only if deferred from M3 |

### Multi-camera and multi-location: decide now, build later

| Decide early (cheap now, costly to retrofit) | Where | Can wait |
|---|---|---|
| `restaurant_id` and `camera_id` on every event and config row | S0-05, BE-101 | Fusion logic across cameras (L-406) |
| Zones link cameras to tables many-to-many | BE-101 | UI for mapping one table on two cameras |
| `organizations` above restaurants; roles on memberships, not users | BE-101 | Organisation admin screens and reports (L-407) |
| Globally unique prefixed IDs; UTC storage with per-restaurant timezone | BE-101 | Cross-location analytics |
| Per-device tokens; restaurant derived from the token | BE-103, BE-301 | Fleet management and remote updates (L-408) |
| Versioned event schema and worker config | S0-05, BE-202 | Mixed-version fleets |
| Stream and queries scoped by restaurant; `LISTEN/NOTIFY` fan-out | BE-105 | Running more than one API instance, partitioning `table_events` |

---

## 9. Release and handoff

**Local setup.** Prerequisites: Git, Docker, Python 3.12, Node 22. `make setup` installs dependencies and git hooks; `make dev` starts Postgres, API and web with hot reload and seeds the demo restaurant; `make simulate`, `make web-mock`, `make test`, `make e2e`, `make cv-eval`, `make contracts` do what their names say. `.env.example` lists every variable; no secrets in the repository.

**Git and review.** Trunk-based. Branch `feat|fix|chore/<issue-id>-short-name` from `main`, open a PR within two working days, squash-merge. One approving review from a different role; CODEOWNERS adds a second for `packages/contracts/` and migrations. PRs aim for under 400 changed lines and state the issue ID, how it was tested, and a screenshot for UI changes. Unfinished features merge behind a settings flag.

**CI on every PR.** Lint and types; unit tests; integration tests with Postgres; contract drift; golden-path E2E; worker smoke test; dev-split CV evaluation when `apps/worker` changes. On `main`: full E2E, held-out CV evaluation, evidence page publish, deploy to staging. Nightly: full E2E against staging, dependency audit.

**Environments.** Local → staging (every merge) → production (git tag `vX.Y.Z`, promoted by D or a deputy after the staging smoke test). The edge agent has its own image tags and is updated separately, never during service.

**Database migrations.** Alembic, run as a pre-deploy step. Changes follow expand-then-contract so the previous release keeps working against the new schema: add first, backfill, switch code, remove in a later release. Each migration has a tested downgrade; destructive steps need a backup taken the same day and a second approval.

**Monitoring.** Error tracker for API and web; uptime check on `/healthz`; structured logs; four numbers on a small status page: heartbeat age per camera, ingest error rate, open stream connections, ingest-to-notify latency. Alerts go to the team channel, and to the on-call phone during pilot shifts.

**Backups.** Managed daily backups plus point-in-time recovery for the pilot tier; one restore drill before launch and one mid-pilot. The edge box holds no data that needs backup; its configuration is re-pulled from the cloud.

**Rollback.** Cloud: redeploy the previous image tag (target under 15 minutes); the expand-then-contract rule means no schema rollback is needed in the normal case. Edge: `./rollback.sh` re-pins the previous image, which stays on disk. Product-level: the "Camera automation off" switch returns the restaurant to manual operation in one tap without any deploy.

**Incident ownership.** D owns the incident process; a named primary and secondary cover each pilot shift on a rota of all four. Severity 1 (dashboard unusable in service): respond in 15 minutes, restaurant switches to the fallback card. Severity 2 (camera offline or wrong states, manual mode working): respond in the same shift. Severity 3: next working day. Every Severity 1 or 2 gets a short written review within three days.

**What each person needs to get started**

| Person | Needs |
|---|---|
| New developer | Repository access; `README` quick start; `CONTRIBUTING`; `docs/architecture.md`; `packages/contracts/`; the acceptance scenarios; a first issue labelled `good-first`; staging credentials for a seeded user |
| Demo reviewer | The demo URL; the one-page reviewer guide with the script; the Evidence link. No account or installation |
| Restaurant manager | Invite link for the admin account; a 2-page quick start (map tables, invite staff, daily use); the printed manual-fallback card; the privacy summary and signage text; the support contact and hours; the pilot schedule and what will be measured |

---

## 10. First-week assignments (12 hours each)

| Person | Tasks for week 1 | Output by Friday |
|---|---|---|
| **D — Deployment and quality, scaffold owner** | S0-01 scaffold and merge to `main` by mid-week (10 h); S0-13 place hardware orders and open the pilot conversation (2 h). S0-02 and S0-03 follow in week 2 | `main` exists; teammates can run `make dev`; orders placed |
| **B — Backend and data** | S0-04 state machine contract (4 h); S0-05 event and heartbeat schemas with A (4 h); start S0-06 OpenAPI stubs once the scaffold lands (4 h) | Contracts PR open for review by all four |
| **C — Frontend and workflows** | S0-08 workflow map and wireframes (6 h); S0-12 acceptance scenarios (4 h); 30-minute walkthrough with the team and follow-ups (2 h) | Workflow doc and scenarios merged; open product questions filed |
| **A — Computer vision** | S0-10 footage plan, consent form, label format (4 h); first recording session for S0-11 (5 h); review S0-05 and confirm D3 detector choice (3 h) | Consent forms signed; first clips in storage; licence decision recorded |

End of week 1: a 45-minute sync to approve contracts v1 and settle D1–D3. Week 2 completes S0-02, S0-03, S0-06, S0-07, S0-09, S0-11 and holds IC0.

---

## 11. Launch checklists

### Demo launch

- [ ] Release tagged; production shows the tagged commit hash
- [ ] All required CI jobs green on the tag: unit, integration, contract, tenant isolation, full E2E
- [ ] Held-out CV report published; each target marked met or explained
- [ ] Evidence link opens reports for the deployed commit
- [ ] Demo template contains synthetic data only; staged clips have signed consent on file
- [ ] Start demo, scenario, clear, seat, offline scenario and reset each work three times in a row on laptop and tablet
- [ ] Two simultaneous viewers verified independent, by automated test and once by hand
- [ ] Sandbox cleanup job and rate limit verified in production
- [ ] Error tracking and uptime alert verified with a forced test
- [ ] Demo script rehearsed by someone outside the team; reviewer guide sent with the URL
- [ ] Rollback to the previous tag tested on staging
- [ ] Known limitations listed in the reviewer guide

### Pilot launch

- [ ] Pilot agreement signed, covering data handling, evaluation recordings, support access and remote access (D6, D8)
- [ ] Guest signage in place; privacy summary given to the manager
- [ ] Site survey complete: mount position, power, network, table sight lines, lighting at service time
- [ ] Bench soak (72 hours) passed; soak report filed
- [ ] Security review complete; no open high-severity findings; tenant-isolation job green
- [ ] Backups on; restore drill done; retention jobs running
- [ ] Edge box installed and auto-starts after a power cycle; camera page shows Online
- [ ] Tables, capacities, floor plan and zones mapped by the restaurant admin; calibration still handled per D7
- [ ] On-site evaluation report reviewed; go/no-go recorded at IC7
- [ ] Staff accounts created with correct roles; each shift lead trained; quick start handed over
- [ ] Off-hours rehearsal of the golden path from the live camera passed
- [ ] Fallback drill passed: camera unplugged, staff run two turns manually, recovery without surprise changes
- [ ] Printed fallback card at the host stand with the support number
- [ ] Cloud and edge rollback each rehearsed in under 15 minutes
- [ ] On-call rota published for every pilot shift; alerts reach the on-call phone
- [ ] Audit sessions scheduled (at least three shifts, 40 table-hours); tap logger tested
- [ ] Week-1 baseline metrics and the weekly review meeting agreed with the manager
- [ ] Exit plan agreed: how hardware is removed and how data is exported and deleted if the pilot ends

---

## 12. Verifying this plan and next steps

- **Review:** the team reads §1 (roadmap, decisions D1–D10), §4 (contracts) and §10 (week 1). Those three sections are what must be agreed before work starts.
- **After approval, and only then:** D creates the five GitHub milestones and one issue per backlog row for M0 and M1 (later milestones are created at each milestone review so they reflect what was learned). Creating them needs write access to the repository, which this planning session does not have.
- **Each milestone is verified** by its exit criteria in §3, the acceptance criteria in §7, the requirement-to-test map in §6 and the checklists in §11.
