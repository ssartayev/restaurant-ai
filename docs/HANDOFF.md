# Restaurant Camera handoff

## Read this first

- Snapshot date: 13 November 2026, Hong Kong.
- Base commit: `c8c9f7dbc2663c4faa23c0164da30568c0fc001f` (the original restaurant management service). Working branch: `codex/simplify-floor`. This document describes the working tree, including untracked source files. Review `git status --short`, `git diff HEAD`, and `git ls-files --others --exclude-standard` before packaging or handing work to another agent. A diff alone omits the new files.
- The app is a local prototype with a working order-to-kitchen loop, recorded-video analysis, and an RTSP edge ingestion path. It needs an on-site vision and operational pilot before production use.
- The baseline `AGENTS.md` explains tenant rules, state-machine behavior, and original engineering decisions. Its original web file map, port, test counts, and some verification statements describe the base commit. The run instructions and source map below describe the current branch.
- The Instagram reference shows camera overlays, service reminders, clearing and turnover, a waiting queue, and peak-time reporting. The prototype covers parts of that workflow. It has no browser feed for a physical live camera, verified waiter recognition, or cross-shift forecasting.

## Run and demonstrate

1. Use Python 3.11+ (verified locally with 3.12), Node 20+, make, and curl. From the repo root run `make video-setup` once. It creates the virtual environment, installs JS and Python packages, and fetches YOLOX-S and MediaPipe Lite into `.models/`.
2. Run `make dev` and open `http://127.0.0.1:8002/`. Override the port with `VIDEO_PORT`. On a fresh checkout, the default database is local SQLite. This workspace has a local PostgreSQL cluster. Restart instructions are in [README](../README.md).
3. Use **Start sample restaurant** for an isolated, seeded tenant with table and report history. Demo sessions expire after 24 hours. For a real deployment disable dev seeding and replace demo onboarding with restaurant provisioning.
4. On **Live board**, mark a table occupied or ready, add a waiting party, or send a dish to the kitchen. On **Kitchen**, progress a ticket through Preparing, Ready and Served. In **History**, choose a range and inspect arrival and service timing patterns. In **Assistant**, run a Weekly, Monthly, or Yearly summary, then reload to see the saved exchange. Typed Gemini questions require `GEMINI_API_KEY` and `GEMINI_MODEL` in the server environment. No credentials belong in Git.
5. On **Recordings**, upload a browser-playable H.264 MP4 up to 250 MB. Wait for analysis, then play or seek. Select a marker to rename it, switch to **2D floor plan**, and drag or move it with arrow keys. The name is shared between views and positions in the floor plan are independent of the footage.
6. On **Cameras**, provision a table and camera, save the one-time token in a private worker file, and configure zones using normalized image coordinates. For the edge launch command and stream URL configuration, see the README. Use a real HTTPS backend URL when the worker is on a separate host. On-site workers are the only processes that need RTSP credentials.

## Architecture and storage

| Surface | Current implementation |
|---|---|
| Browser | React 18, TypeScript, Vite. `main.tsx` is the recording-review view and SPA entry point. `Operations.tsx` owns navigation, sessions, Live board, Kitchen and Cameras. `Insights.tsx` owns History, Assistant and the shared JSON request helper. `video.css` contains the light restaurant palette, responsive layout, and reduced-motion support. |
| Web server | `apps/api/app/video.py` is the default local FastAPI entry point. It serves `POST /analyze`, includes the existing management routes, runs their lifespan, and serves the built SPA. `app.main:app` remains the management-only entry point with API and built SPA. |
| Operational data | `app/models.py`, `db.py`, and `service.py`. SQLAlchemy on SQLite or PostgreSQL. Tenant-owned data is scoped by restaurant membership; device requests use a hashed camera token. Database timestamps are UTC. API reads are role-scoped, and calendar ranges use the restaurant time zone. |
| Live video | `apps/worker/worker/agent.py` opens RTSP on the edge, samples frames, and sends JSON through `transport.py`. No frame, face ID or track ID is sent through edge ingest. A local SQLite queue retries occupancy events. Heartbeats reconcile state and carry latest tableware and presence evidence. Browser refreshes floor and order snapshots on SSE, with polling fallback. Event fan-out is in-process and assumes one API process. |
| Recording vision | `app/video.py` samples approximately once per second and uses YOLOX-S for people, dining tables and COCO tableware classes. `app/pose.py` runs MediaPipe Lite per person crop, estimates sitting from knee geometry and rejects some leaning/reaching poses. `app/table_activity.py` assigns likely diners to the nearest table, matches points between samples, and smooths presence. Overlay evidence is aligned to playback seconds. |
| Tableware | `worker/tableware.py` assigns a detection center to one table box. The worker associates detected surfaces with configured table zones. Recorded overlays now require repeated evidence using a short median window. This is a count of visible items, with no inference of dirt or readiness. |
| Reports and AI | `app/analytics.py` computes calendar periods, occupancy, completed turns, peak weekday/hour, and medians for prep, pickup and reset. `app/report_chat.py` handles deterministic summary shortcuts and optional server-side Gemini responses. Admin report and chat routes are in `app/main.py`. |

The live table state model remains Ready → Occupied → Needs clearing → Ready. Staff must confirm Ready. The live worker still uses the original presence filter with 20-second arrival and 75-second departure windows by default. Recording review has a different pose and temporal pipeline, so the two paths can disagree. After camera loss the backend waits for agreement before trusting camera-driven state changes on held tables.

The schema persists restaurants, memberships, sessions, tables, cameras, zones, alerts, waitlist parties, and timestamped table events. The branch adds:

- `order_tickets`: table and server association, item list, sent/preparing/ready/served timestamps. The API enforces forward stage changes. Served tickets are omitted from the active kitchen list.
- `table_bills`: one open bill per table, opened/paid timestamps. Creating a ticket opens the bill. Host or admin can record payment. No actual payment transaction is processed.
- `table_observations`: latest table-level presence and tableware evidence with camera and observation time. Changes in tableware counts also enter event history.
- `report_exchanges`: admin identity, question, report snapshot and selected mode, timestamp, and optional answer. A failed request can have a stored question with no answer. The Assistant shows up to 100 exchanges for that restaurant and user. Prompt shortcuts are deterministic; typed questions use Gemini as independent requests with the selected aggregate report. There is no multi-turn reasoning context or arbitrary query tool.

Local database history: SQLite `dev.db` is retained. PostgreSQL 17 was installed for this workspace and uses a private local Unix socket on port 55432. An earlier test configuration inherited the operational database URL and reset its schema. The available SQLite snapshot was restored into `restaurant_ai_restored`; records exclusive to the old PostgreSQL instance could not be reconstructed from that snapshot. The Makefile now uses the restored database when the local cluster exists, and tests default to disposable SQLite. The API test fixture drops and creates tables; a PostgreSQL override must explicitly use a disposable database ending in `_test`. The local cluster, media, models, SQLite databases, and secrets are excluded from Git. Demo rows are still subject to normal expiry. No migration framework is configured, so startup creates missing tables but cannot perform arbitrary column migrations.

## Changes since the base commit

- Replaced the original demo dashboard, setup and analytics frontend with recording review and a separate operational SPA. The original backend state machine, demo replay, roles, and fixtures remain available. The original dashboard source can be recovered from the base commit if needed.
- Added upload analysis with automatic table IDs, timed occupancy and counts, approximate 2D floor layout, per-session drag/rename, table capacity, waitlist and reset controls, tableware overlays, and recording metrics.
- Added the default Live board, database-backed kitchen ticket lifecycle, manual table and payment actions, waitlist matching, camera onboarding and rectangular zone entry, admin-only delayed payment alert, and queue-aware reset priority. The last selects a clearing table that fits a waiting party and has no open bill.
- Added calendar reports, custom date ranges, order timing summaries, database-backed Assistant history, and optional Gemini configuration. The current pass adds saved key-free report shortcuts and a manual chat composer.
- Redesigned around dark navigation, warm cream/terracotta content surfaces, clear status colors, a two-column floor and queue layout, a History heatmap and median timing bars, chat bubbles, and subtle entrance/bar animations. Reduced-motion preferences disable animation. Design references include [Digital of Things](https://www.awwwards.com/sites/digital-of-things), [Linear](https://linear.app/), [Higgsfield](https://higgsfield.ai/), and [Geist](https://vercel.com/geist/introduction). No theme framework or chart dependency was added.
- Fixed report boundary accounting for already-occupied tables, debounced tableware evidence on recordings, updated the OpenAPI and heartbeat contracts, and updated CI and browser tests for the current app. CI configuration was edited locally and still needs a GitHub run after a push.
- For the exact file inventory, run `git diff --name-status HEAD` and `git ls-files --others --exclude-standard`. Removed frontend modules are `App.tsx`, `Dashboard.tsx`, `Analytics.tsx`, `Setup.tsx`, `api.ts`, and `styles.css`. The new frontend files are `Operations.tsx`, `Insights.tsx`, and `video.css`. New backend/vision files are `video.py`, `pose.py`, `table_activity.py`, `report_chat.py`, and `worker/tableware.py`.

## Verification and vision evidence

- `make test` passed 66 API tests on SQLite, 22 worker tests, and the web type-check. A Starlette test-client deprecation warning remains.
- `TEST_DATABASE_URL=… make test-api` passed 66 API tests using an isolated PostgreSQL 17 database. The operational database was outside this test.
- `CCTV_TEST_VIDEO=/path/to/Cctv-Resturant-Demo.mp4 make e2e` passed invalid upload handling, real CCTV analysis, floor/camera table parity, dragging, renaming, kitchen ticket lifecycle, History heatmap, saved weekly shortcut across reload, and the mobile composer. Install the browser with `cd e2e && npm install && npx playwright install chromium` if needed. The Gemini response integration was tested with a stub in the API suite. No live Gemini request was verified.
- Desktop screenshots of the Live board, History, and a saved Monthly summary were inspected in Chromium. The monthly summary also wrote to the PostgreSQL-backed local app through a temporary demo tenant. No permanent screenshot artifacts are required to build.
- An earlier pass sent real-frame YOLOX tableware evidence through the edge agent to the PostgreSQL-backed live board. This establishes the transport path. It does not validate an actual physical RTSP feed over a full shift.
- The original `make cv-eval` exercises synthetic traces and reports the baseline zone/filter metrics. It does not evaluate the recording pose model or tableware class accuracy.

Current local vision smoke results. A positive tableware sample means one table at one sampled timestamp had a nonzero count. These clips are not a labeled detection benchmark.

| Clip | Tables found | Sampled timestamps | Positive tableware samples | Peak estimated seated |
|---|---:|---:|---:|---:|
| User CCTV | 6 | 44 | 22 | 6 |
| [Busy waitstaff](https://www.pexels.com/video/busy-restaurant-scene-with-waitstaff-serving-39890727/) | 0 | 7 | 0 | 0 |
| [Overhead dining](https://www.pexels.com/video/top-view-of-people-eating-their-food-4821100/) | 1 | 9 | 8 | 3 |
| [Seaside dining](https://www.pexels.com/video/people-eating-at-the-seaside-restaurant-5001580/) | 2 | 13 | 0 | 0 |

The original 44-second recording ran in about five seconds on this Mac in a direct analysis call. This excludes upload time and is not a throughput guarantee. At 0:16 and 0:20, the supplied clip gives two diners at T3. At 0:30 it undercounts that table. A dimmed/blurred copy still undercounts at several checkpoints. An artificially occluded copy still produces a duplicate table and misses diners around the obstruction. MediaPipe Full was previously benchmarked on those variants and did not consistently improve counts. Stock footage and local CCTV are not committed.

## Known problems and priorities

### Before showing judges

- Use the sample restaurant and a tested clip. Explain that the board uses persisted live operational data, while uploaded recording review has its own session and camera timeline. Names, layout positions, and staff actions from recording review do not populate the operational database. Recording review can use the same device/browser even when operational auth is absent; it should stay local until an authenticated upload design is implemented.
- Use the exact **Weekly summary** shortcut to demonstrate saved chat without credentials. For live free-form Q&A configure a Gemini model and key on the backend. Questions requiring revenue, payments, dish-level timings or staffing assignments cannot be answered from the current report. Reports can distinguish missing medians from zero tickets; occupancy uses all elapsed calendar time, not staffed opening hours.
- Avoid implying that a clean table or unpaid departure is proven by vision. Tableware is supporting evidence. An admin payment check uses a manual bill record and five minutes of fresh camera vacancy; a new presence detection cancels it. Staff remain responsible for confirming payment and readiness.
- The demo uses quick setup and existing data. Camera zones currently require normalized rectangle entry, rather than drawing directly on a calibration image.

### Before a restaurant pilot

1. **Unify occupancy inputs.** Bring the better validated seated-person approach to live RTSP, add persistent tracks only in edge memory, add true per-table camera calibration, and evaluate camera motion, occlusion, low light, seated staff, guests standing up, and people waiting near the tables. Current live raw presence can be affected by passersby and cleaning staff.
2. **Make vision quality measurable.** Collect consented clips and table-level labels from several different venues. Split by restaurant/camera. Measure table precision/recall, diner count error, false departures, false staff alerts per table-hour, and detection delay. Evaluate COCO detectors and pose models as candidates, then fine-tune for dishes/plates and restaurant layouts only if the held-out data shows a gain. No new training or classifier for dirty dishes exists. The current general detector has no dedicated plate class and cannot see crumbs or stains.
3. **Harden live ops and notifications.** Validate RTSP with a real camera, missed heartbeats, network and power loss, and a full-shift soak. Add camera calibration UI, worker packaging and recovery. Decide whether a LAN-only video preview is necessary. Maintain a manual fallback when vision or connectivity fails. Resolve multi-camera fusion and overlapping zone semantics before adding multiple cameras over the same table.
4. **Complete payments and kitchen controls.** Add explicit dining sessions and bill/order association, payment integration or reconciliation, order cancellation/voids, menu and modifiers, dedicated kitchen permissions, assigned-server notifications, and idempotent order submission. The current manual paid action does not verify a POS receipt. Kitchen actions currently reuse staff membership.
5. **Strengthen analytics.** Record opening hours, camera coverage, actual seat/party counts, alerts and confirmations. Add samples and provenance to every metric, hourly report drill-downs, historical floor layouts, and transparent comparisons with an appropriate earlier period. Test reports through daylight-saving changes and offboarding. Occupancy currently divides by current table count times calendar elapsed time.
6. **Secure and deploy.** Add Alembic, backups and restore tests, auth/rate limits, deployment configuration, monitoring, error reporting, dependency/model license review, and Gemini rate/timeout controls. The app uses one SSE process. Docker/Compose in the base still launch the management service, not the default recording-capable app with model dependencies. No public deployment is verified. Do not send camera frames or identity information to the management server or the assistant. Review the data retention policy for order and chat records before a real tenant is provisioned.

### Product follow-up

- The strongest current demo is the queue-aware reset recommendation. Put a waiting party on the board, clear the fitting table, mark it ready, and seat them. Measure time saved in a pilot before claiming an advantage.
- Opt-in shared seating (搭枱) is a useful candidate for small, dense venues. Model seats and distinct dining sessions, so two parties can share a physical table with independent kitchen tickets and bills. This is a proposal, not shipped.
- Add an auditable service timeline linking seating, first order, kitchen ready, served, departure, and reset. An AI answer should show the underlying period, sample counts, and links to source reports. The current assistant has aggregate reports and saved transcripts, with no event drill-down.
- Closest overlapping tools include [Lightspeed Tempo](https://k-series-support.lightspeedhq.com/hc/en-us/articles/43687798096027-Understanding-Lightspeed-Tempo), [Eats365](https://www.eats365pos.com/hk/en/expansion-module/scan-order-byod), and [SevenRooms](https://sevenrooms.com/platform/table-management/). Do not claim that table pacing, kitchen status, AI chat or waitlists are unique by themselves.

## Practical commands and contracts

- `make openapi` regenerates `packages/contracts/openapi.json` after route changes. Keep `packages/contracts/events/heartbeat.v1.schema.json` aligned with `ZoneState` and edge serialization.
- `make api` starts the management API on port 8000. `make web` serves Vite on 5173 and proxies that API. Use `make dev` for full recording analysis. `make simulate` targets the management API path.
- `make clean` deletes local SQLite development files and build artifacts. Do not run it on a workspace with data that needs preserving.
- For new operational endpoints use `Depends(member(...))` and tenant-filter every child lookup. Add a positive-path test alongside tenant isolation tests. Keep the camera state transition contract intact and publish SSE only after the DB write commits.
- Models are sourced from the [YOLOX release](https://github.com/Megvii-BaseDetection/YOLOX/releases/tag/0.1.1rc0) and [Google MediaPipe Pose Landmarker](https://developers.google.com/edge/mediapipe/solutions/vision/pose_landmarker). YOLOX's COCO class list [includes bowl, cup, glass and cutlery](https://huggingface.co/amd/yolox-s/blob/632a5be3e99ff16407a0649e0f0758dccc2bb4aa/coco.py), without a plate class.

## Mise visual identity — latest revision, 13 November 2026

The latest user feedback explicitly releases the white-only constraint. Beige/terracotta was rejected as boring; native file inputs and the monolithic camera configuration form were specifically called out. The requirement is a distinctive, modern, understandable product suitable for hackathon judging, with consistent branding and restrained animations. The design must support staff work, not add operational complexity.

The working product name is **Mise**, from mise en place, with the line **The service of flow**. This is a proposed product identity, not a cleared trademark or registered domain. A CSS-drawn rounded table with four seats is its mark. Midnight navy (#12243a / #18314d) establishes navigation and primary actions; chartreuse (#d2f86a) is reserved for brand accents, active navigation and uploading; cool mist (#edf1f5) and white form the work surfaces. Occupancy/clearing colors remain semantic rather than all becoming brand colors. The mark and room motif are authored in code with no stock imagery or external assets.

Changes in this revision:
- Rebranded shared navigation and browser title; retains all routes and role gates.
- Replaced warm colors across reports, chat, cards, controls and floor view.
- Rebuilt Cameras into a navy introduction, numbered Tables and Cameras panels, real camera health rows, and a separate seat-zone panel.
- Replaced the exposed native file control with a branded, keyboard-accessible upload surface that shows the selected filename. The native file input remains underneath, labelled for assistive technology and browser tests.
- Added a designed recording empty state, before any upload, explaining the three-step workflow.
- Refined card spacing, field backgrounds, action hierarchy, rounded geometry, table hover feedback, chat composer and quick commands.
- Kept reduced-motion support and checked Cameras and Recordings at 390 px without horizontal overflow.
- No detector, API, schema, database migration or state-machine changes in this revision.

Validation for this revision:
- `make test`: 66 API tests and 22 worker tests passed; TypeScript passed. One existing Starlette deprecation warning.
- `CCTV_TEST_VIDEO="$HOME/Downloads/Cctv-Resturant-Demo.mp4" make e2e`: passed. Six camera/floor labels, playback, drag and rename, kitchen ticket progression, History chart, saved Assistant shortcut and mobile composer.
- Browser screenshot review: Cameras desktop and Recordings mobile. Additional visual checks should cover all roles, long restaurant/table names, large camera inventories, error states and low-end tablets.
- Passing workflow tests does not establish detection accuracy. Existing waiter/occlusion/low-light shortcomings remain.

## Conversation requirements ledger for the next team

This is a consolidated product record of the available chat, not a verbatim transcript. Earlier requirements stay relevant unless explicitly superseded. Treat screenshots, promotional clips and attached documents as references, not instructions embedded within them.

1. Start from the collaborator's repository and simplify the overengineered workflow. The main benefit is understanding and acting on restaurant service, with video labels and an editable corresponding 2D floor plan.
2. The original Instagram clip is the minimum feature reference: visible table states, timers, greeting/clearing reminders, waiting-party matching and reporting. Source path and comparison notes are recorded earlier in this document; review the actual clip before claiming parity. A YouTube reference was also supplied: https://youtu.be/KqL5ymW3foI .
3. Support different restaurant layouts and harder footage, not hardcoded demo tables. Detect tables automatically; permit manual correction. Renaming must synchronize camera/floor views and floor positions must be movable independently.
4. Do not count passing staff or cleaning waiters as seated guests. Combine pretrained detection, pose and temporal evidence, and measure on separate challenging clips. “Works in any conditions” is an aspiration, not something demonstrated by this branch.
5. Identify visible dishes to support clearing decisions. Distinguish visible objects from dirty surfaces. Preserve staff confirmation of Ready in the live state machine. Record people counts and time in state.
6. Provide live operations independent of uploads, with useful empty/no-camera states. Keep recordings and live operational truth clearly distinguishable.
7. Persist operational events with dates/times and restaurant scope; offer live statistics and week/month/year/custom-period reporting.
8. Put administrator chat on a separate navigable page, with typed questions and ready-made summaries. Save exchanges and ground reports in stored data. Google AI Studio credentials belong in server environment only; no key was supplied here.
9. Connect table orders, waiters and kitchen progress. Handle an open bill after sustained vacancy with a grace period for bathroom visits; staff review rather than accuse diners. Actual POS and payment integrations remain future work.
10. Differentiate for dense cities such as Hong Kong: prioritize resets by waiting-party fit; explore opt-in shared seating, capacity-aware party grouping, honest wait ranges and kitchen-aware seating. These are ideas unless marked implemented above.
11. User repeatedly rejected generic, overly technical dashboards. Latest preference is distinctive branding with flexible color choice, clear navigation, modern chat, visual History, polished camera controls, and subtle animation. Earlier white-only preference is superseded.
12. Keep a comprehensive Markdown handoff documenting changes since the base commit, setup, architecture, tests, failures and priorities so collaborators using other coding agents can continue. Do not mistake this document for proof that every requested capability exists.

## Next design and product improvements

- Replace normalized coordinate entry with an edge-local camera zone drawing UI, preserving the prohibition on transmitting frames through live ingest. The current numerical editor is still a usability limitation.
- Consolidate video.css's historical cascaded rules into a single token/component stylesheet before another major theme change. Avoid adding another parallel component system solely for styling.
- Add a custom favicon, verify font availability across platforms, and clear name/domain/trademark availability before publishing the Mise identity.
- Extend visual regression coverage across all pages and states; include keyboard navigation, contrast measurements and screen-reader review.
- Add setup completion feedback, editable camera/table configuration and clearer recovery paths, with authorization and tenant-isolation tests for every new route.
- Resolve the vision and production readiness gaps in the earlier sections first: trained restaurant-specific evidence, held-out footage, real RTSP soak testing, POS-backed bills, migrations/backups, and the live/recording pipeline mismatch.
- Product claims for judges should separate measured implementation, local demonstrations and planned differentiators. Do not market the current branch as production-ready or as having reliable waiter identity/cleanliness recognition.

## Latest palette and object overlays

The user's five-blue reference supersedes the chartreuse Mise palette: midnight #03092c, ocean #0c3a68, royal #102774, deep #061e51, sky #106da4, with white and pale surfaces. The Mise name and table-shaped mark remain. No yellow brand accent remains; semantic amber cleaning warnings are operational status, not branding.

Recording analysis now returns timestamped normalized object boxes, class labels and detector confidence. Camera playback shows Table, Person / Seated person, Glass, Cup, Fork, Knife, Spoon and Bowl when detected. Table ID buttons remain selectable; the operational status/count/timer cards belong to the 2D view. The boxes refresh at sampled timestamps (about 1 Hz), not full-frame tracking. No waiter classifier has been added, and “Seated person” does not prove a client role. The model does not have a plate class or prove cleanliness. Camera confidence percentages are object detector scores, not role confidence.

This implements object overlays on uploaded recording playback only. The requested true live-video object overlay is still outstanding: the browser currently has no RTSP/WebRTC video surface and the live edge contract intentionally excludes boxes/images/track IDs. A future implementation should render annotations on the restaurant's edge/local viewer or introduce a separately secured, explicitly designed stream; do not smuggle frames or person coordinates into the table-level cloud event schema. No identity recognition is required.

## Website handbook: how to use every page

### Start and sign in
Run `make dev` and open http://localhost:8002. Sign in with a staff account, or choose **Start sample restaurant** for an isolated temporary demo. Sample data is artificial and the sandbox expires after 24 hours. Available navigation depends on your role; History, Assistant and Cameras require administrator access. Sign out using the page-header button.

### Live board
This is the daily operational view. The top counters show occupied, ready and clearing tables and waiting parties. Table cards show capacity and current state. Use **Mark occupied**, **Party left**, and **Mark ready** to correct the floor manually. Camera evidence never confirms Ready for you. Add a party name and size in Waiting parties; **Seat at …** confirms a suggested table. The reset-priority hint highlights a table that fits a waiting party. Open-bill alerts request staff review after a grace period; use **Acknowledge**, check the situation, and **Mark bill paid** only after actual payment. This button records payment status; it does not charge a customer. To place an order, select a table, enter a dish and quantity, then choose **Send to kitchen**. The page works without a camera.

### Kitchen
Find the ticket by table and dish. Progress it with **Mark preparing**, **Mark ready**, then **Mark served**. Served tickets leave the active list. These timestamps contribute to reporting. This is a basic internal ticket workflow, not an integrated commercial POS.

### Recordings
Choose a browser-playable restaurant video (prefer H.264 MP4, maximum 250 MB), wait for analysis, then play, pause or seek. Camera view shows object rectangles and detector scores. Select a table ID to edit its number in the side panel. **2D floor plan** shows table status, estimated diners and timers; drag tables or use arrow keys after selecting one. Renaming is shared across the two views; moving a floor-plan table does not move its camera location. Set capacities, review reminders and use recording-local staff controls as needed. Expand **Recording statistics** for estimates. Recording edits and waiting parties are local to this review and reset on reload/new upload; they are not the operational restaurant database. Detection is sampled and fallible: people are not reliably classified as waiters or clients, and detected dishes do not establish dirt. Uploaded video is analyzed on this server; it is not the edge-only live workflow.

### History
Choose week, month, year or a custom date interval. Inspect occupancy/turn counts, weekday-hour arrivals and service-time charts. Reports use persisted operational events and restaurant-local calendar ranges, not recording-review actions. Empty or missing values mean there may be insufficient evidence; they are not proof of zero activity. Only administrators can access this page.

### Assistant
Use **Weekly summary**, **Monthly summary** or **Yearly summary** for a saved report without an AI key. Select the reporting period, type a question, and choose **Send** for a free-form request. This requires server-side GEMINI_API_KEY and GEMINI_MODEL configuration. Questions and answers are stored and reappear after reload. The assistant currently receives aggregate reports, not unrestricted database access or a full conversation memory; it cannot answer unsupported revenue/POS questions reliably. Only administrators can access this page.

### Cameras
1. Under Tables, enter a table number/name and seat count, then **Add table**.
2. Under Cameras, enter a camera name and choose **Add camera**. Securely save the one-time device token for the edge worker; never commit it. Camera rows display connection and image health.
3. Under Seat map, select a camera and table. Enter left/top/right/bottom coordinates normalized from 0 to 1, with right greater than left and bottom greater than top. Choose **Save camera zone**. Map seats carefully to avoid counting passers-by.
4. Configure and run the local RTSP worker using the README instructions. Provisioning a camera here alone does not connect the hardware.
This page has no live video player or visual zone drawing yet. A real camera installation still requires a local worker and calibration.

Latest verification after blue palette and object overlays: `make test` passed (66 API, 22 worker, TypeScript); `CCTV_TEST_VIDEO="$HOME/Downloads/Cctv-Resturant-Demo.mp4" make e2e` passed, including newly added assertions that object rectangles appear in Camera and are absent from the 2D floor plan. Six tables appeared in both views. `git diff --check` passed. This validates workflow, not role-classification accuracy or live streaming.

Overlay placement regression fixed: a broad text replacement had duplicated object rendering inside Staff alerts, positioning a second set against the page. Removed that duplicate. Browser coverage now asserts every object box belongs to the camera and its bounds remain within the video. Verified with the actual CCTV upload and a full-page screenshot (zero boxes outside camera). `make test` passed (66 API, 22 worker, TypeScript); CCTV `make e2e` passed. This is a rendering fix, not a change in detector accuracy.
