# Restaurant Camera

Upload a fixed-angle restaurant recording and review estimated table occupancy as it plays. The app samples frames with YOLOX-S, groups repeated dining-table detections into stable labels, and estimates occupancy from people near each table. It runs locally and removes the temporary recording after analysis.

## Run locally

Requires Python 3.11+, Node 20+, make, and curl.

```bash
make video-setup
make dev
```

Open http://localhost:8002 and choose a browser-playable MP4 up to 250 MB. Wait for analysis, then play or seek through the recording. Use `make dev VIDEO_PORT=8003` if the default port is busy.

Table discovery and occupancy are estimates. Small, obscured, or unusual tables can be missed. Vacant means no nearby person was detected consistently. This app does not infer cleanliness or service status.

## Staff operations and storage

Open http://localhost:8002/operations for the live board, kitchen tickets, and historical reports. The management service persists table events and ticket timestamps. Recording review remains separate from operational history.

The default development database is SQLite. If the workspace PostgreSQL cluster has been initialized, `make dev` uses it via a private Unix socket. If it is stopped, restart it from the repo root:

```bash
"$(brew --prefix postgresql@17)/bin/pg_ctl" -D .local-postgres/data \
  -l "$PWD/.local-postgres/server.log" -o "-h '' -p 55432 -k '$PWD/.local-postgres/socket'" -w start
make dev
```

To use a different PostgreSQL instance, install `apps/api[postgres]` in the project virtual environment and set `DATABASE_URL` to a `postgresql+psycopg://` connection string. Keep credentials outside Git. The workspace cluster and SQLite files are ignored by Git.

## Live camera and payment checks

The live board opens at http://localhost:8002 without a recording. In **Cameras**, an administrator can add a table, pair a camera, and set its table zones. Use a zone that covers the seats and tabletop, with coordinates normalized to the camera frame. Save the one-time device token to a private file outside Git on the on-site worker.

From the repo root on the worker, with the video dependencies installed:

```bash
PYTHONPATH=apps/worker .venv/bin/python -m worker.agent \
  --api http://127.0.0.1:8002 --token-file /path/to/private-device-token \
  --source rtsp://camera.local/stream1 --model .models/yolox_s.onnx
```

Use the backend's reachable HTTPS URL when the worker runs on a different host. The live board receives table and camera status. Camera pixels stay on the worker. The recording review page still runs locally for uploaded files.

A table order opens a bill. Hosts and admins close it with **Mark bill paid** after verifying payment. With fresh camera evidence of continuous vacancy, the admin board prompts a payment check after five minutes by default (`BILL_CHECK_GRACE_S`). A returning person resets the timer. No payment is processed by the app.

YOLOX tableware counts are supporting evidence for clearing. A count of zero does not certify cleanliness. Staff confirm readiness. The reset suggestion prioritizes a table that fits a waiting party and has no open bill.

The Assistant page stores the question, report snapshot, timestamps, and generated answer. Set `GEMINI_API_KEY` and `GEMINI_MODEL` in the backend environment to enable generation. Failed requests still appear in history without an answer.

For the updated page-by-page usage handbook, active-footage workflow, waiter marking, architecture, known limitations, testing evidence and commit history, see [the Mise handbook and developer handoff](docs/HANDOFF.md).
