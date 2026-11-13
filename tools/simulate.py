#!/usr/bin/env python3
"""Replay a scenario file against a running API over HTTP (standard library only).

Camera steps use the device token, exactly like the edge box. Staff steps sign in as
the seeded users. With --assert, "expect" steps are checked and a mismatch exits 1.

  python tools/simulate.py dinner_basic --speed 20 --assert
"""
import argparse
import http.cookiejar
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOGINS = {"admin": ("admin@demo.test", "demo-admin"), "host": ("host@demo.test", "demo-host"),
          "staff": ("staff@demo.test", "demo-staff")}


class Http:
    def __init__(self, base, token=None):
        self.base, self.token = base.rstrip("/"), token
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, method, path, body=None):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(self.base + path, method=method, headers=headers,
                                     data=None if body is None else json.dumps(body).encode())
        try:
            with self.opener.open(req, timeout=10) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scenario")
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--token-file", default=str(ROOT / ".dev-device-token"))
    ap.add_argument("--speed", type=float, default=10)
    ap.add_argument("--assert", dest="check", action="store_true")
    args = ap.parse_args()

    steps = [json.loads(line) for line in
             (ROOT / "fixtures" / "scenarios" / f"{args.scenario}.jsonl").read_text().splitlines() if line.strip()]
    device = Http(args.api, Path(args.token_file).read_text().strip())
    users = {}
    for role, (email, pw) in LOGINS.items():
        users[role] = Http(args.api)
        code, _ = users[role].call("POST", "/v1/auth/login", {"email": email, "password": pw})
        if code != 200:
            sys.exit(f"cannot sign in as {email}: start the API with SEED_DEV=1 (make dev)")
    _, me = users["admin"].call("GET", "/v1/me")
    rid = next(m["restaurant_id"] for m in me["memberships"] if not m["is_demo"])
    floor = lambda: users["admin"].call("GET", f"/v1/restaurants/{rid}/floor")[1]  # noqa: E731
    table = lambda label: next(t for t in floor()["tables"] if t["label"] == label)  # noqa: E731
    now_iso = lambda off=0: (datetime.now(timezone.utc) + timedelta(seconds=off)).isoformat()  # noqa: E731

    def beat(zones):
        return device.call("POST", "/v1/ingest/heartbeat", {
            "schema_version": 1, "type": "camera.heartbeat", "sent_at": now_iso(), "zones": zones})

    beat([])  # the camera is online
    clock, last, failures = 0.0, None, []
    for i, s in enumerate(steps, 1):
        time.sleep(max(0.0, (s.get("t", 0) - clock) / args.speed))
        clock, do = s.get("t", 0), s["do"]
        if s.get("note"):
            print(f"[{clock:>5.0f}s] {s['note']}")
        if do == "camera":
            _, out = device.call("POST", "/v1/ingest/events", {"events": [{
                "schema_version": 1, "type": "occupancy.changed", "table_id": table(s["table"])["id"],
                "event_id": s.get("event_id") or "evt_" + uuid.uuid4().hex[:20],
                "occupied": s["occupied"], "observed_at": now_iso(s.get("observed_offset_s", 0))}]})
            last = out["results"][0]["result"]
        elif do == "heartbeat":
            z = s.get("zones", "agree")
            zones = ([{"table_id": t["id"], "occupied": t["state"] == "occupied"} for t in floor()["tables"]]
                     if z == "agree" else [{"table_id": table(k)["id"], "occupied": v} for k, v in z.items()])
            beat(zones)
        elif do == "camera_online":
            beat([])
        elif do == "camera_offline":
            print("        (over HTTP an outage means: stop sending heartbeats for 45 s; skipped)")
        elif do == "staff":
            t = table(s["table"])
            code, out = users[s.get("as", "staff")].call(
                "POST", f"/v1/restaurants/{rid}/tables/{t['id']}/commands",
                {"command": s["command"], "expected_version": t["version"] - (1 if s.get("stale_version") else 0)})
            last = "conflict" if code == 409 else out["result"]
        elif do == "ack":
            t = table(s["table"])
            a = next((a for a in floor()["alerts"] if a["table_id"] == t["id"] and a["status"] == "open"), None)
            if a:
                last = users[s.get("as", "staff")].call("POST", f"/v1/restaurants/{rid}/alerts/{a['id']}/ack")[1]["result"]
        elif do == "seat":
            t, f = table(s["table"]), floor()
            p = next(p for p in f["waitlist"] if p["name"] == s["party"])
            code, _ = users[s.get("as", "host")].call(
                "POST", f"/v1/restaurants/{rid}/tables/{t['id']}/seat", {"party_id": p["id"]})
            last = "applied" if code == 200 else "conflict"
        elif do == "add_party":
            users["host"].call("POST", f"/v1/restaurants/{rid}/waitlist", {"name": s["name"], "party_size": s["size"]})
        elif do == "expect" and args.check:
            f = floor()
            errs = []
            if "last_result" in s and last != s["last_result"]:
                errs.append(f"last_result {last} != {s['last_result']}")
            if "table" in s:
                t = next(t for t in f["tables"] if t["label"] == s["table"])
                for k in ("state", "manual_hold"):
                    if k in s and t[k] != s[k]:
                        errs.append(f"{s['table']}.{k} {t[k]} != {s[k]}")
                alerts = [a for a in f["alerts"] if a["table_id"] == t["id"]]
                if "open_alerts" in s and len(alerts) != s["open_alerts"]:
                    errs.append(f"{s['table']} alerts {len(alerts)} != {s['open_alerts']}")
                if "suggestion" in s:
                    sug = next((x for x in f["suggestions"] if x["table_id"] == t["id"]), None)
                    name = next(p["name"] for p in f["waitlist"] if p["id"] == sug["party_id"]) if sug else None
                    if name != s["suggestion"]:
                        errs.append(f"{s['table']} suggestion {name} != {s['suggestion']}")
            for e in errs:
                print(f"  FAIL step {i}: {e}")
            failures += errs
    if args.check:
        print("FAILED" if failures else "all expectations met")
        sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
