"""Edge transport: a durable local queue and a tiny HTTPS client (standard library only).

Store and forward: every event is written to SQLite first, then sent in batches. If
the internet is down the events wait on disk. The SERVER decides what a late event
means (anything observed more than 120 s ago is kept as history and not applied), so
the edge box never needs to guess.
"""
import json
import sqlite3
import time
import urllib.error
import urllib.request


class EventQueue:
    def __init__(self, path: str = "queue.db", max_rows: int = 50_000):
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS q (id INTEGER PRIMARY KEY AUTOINCREMENT,"
                        " payload TEXT NOT NULL, created REAL NOT NULL)")
        self.db.commit()
        self.max_rows = max_rows

    def put(self, event: dict):
        self.db.execute("INSERT INTO q (payload, created) VALUES (?, ?)", (json.dumps(event), time.time()))
        # Bounded: after a very long outage drop the OLDEST rows; they would be stale anyway.
        self.db.execute("DELETE FROM q WHERE id <= (SELECT MAX(id) FROM q) - ?", (self.max_rows,))
        self.db.commit()

    def peek(self, n: int = 100) -> list[tuple[int, dict]]:
        rows = self.db.execute("SELECT id, payload FROM q ORDER BY id LIMIT ?", (n,)).fetchall()
        return [(i, json.loads(p)) for i, p in rows]

    def ack(self, ids: list[int]):
        self.db.executemany("DELETE FROM q WHERE id = ?", [(i,) for i in ids])
        self.db.commit()

    def __len__(self):
        return self.db.execute("SELECT COUNT(*) FROM q").fetchone()[0]


class ApiClient:
    def __init__(self, base_url: str, token: str, timeout: float = 10.0):
        self.base, self.token, self.timeout = base_url.rstrip("/"), token, timeout

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(
            self.base + path, method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read() or b"{}")

    def config(self) -> dict:
        return self._call("GET", "/v1/worker/config")

    def send_events(self, events: list[dict]) -> dict:
        return self._call("POST", "/v1/ingest/events", {"events": events})

    def send_heartbeat(self, hb: dict) -> dict:
        return self._call("POST", "/v1/ingest/heartbeat", hb)


def flush(queue: EventQueue, client: ApiClient, batch: int = 100) -> int:
    """Send queued events oldest first. Returns how many were delivered. Never raises on network errors."""
    sent = 0
    while True:
        rows = queue.peek(batch)
        if not rows:
            return sent
        try:
            client.send_events([e for _, e in rows])
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 422):   # the server will never accept this batch: do not retry forever
                queue.ack([i for i, _ in rows])
                continue
            return sent
        except (urllib.error.URLError, OSError, TimeoutError):
            return sent                   # offline: keep everything, try again later
        queue.ack([i for i, _ in rows])
        sent += len(rows)
