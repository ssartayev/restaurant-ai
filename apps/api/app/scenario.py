"""Scenario files (fixtures/scenarios/*.jsonl): one JSON step per line.

The SAME file drives integration tests (run_sync with assertions), the hosted demo
(demo.py replays it in real time) and tools/simulate.py (over HTTP).

Step kinds ("do"):
  camera          {table, occupied, event_id?, observed_offset_s?}
  heartbeat       {zones: "agree" | {label: bool}}
  camera_offline / camera_online
  staff           {table, command, as?, stale_version?}
  ack             {table, as?}
  seat            {table, party, as?}
  add_party       {name, size}
  note            (narration only)
  expect          {table?, state?, manual_hold?, open_alerts?, alert_status?, suggestion?,
                   party_status?, last_result?, camera_status?}
"""
import json
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config, service
from .models import Alert, Camera, Membership, Restaurant, Table, User, WaitlistParty
from .util import new_id


def load(name: str) -> list[dict]:
    path = config.FIXTURES_DIR / "scenarios" / f"{name}.jsonl"
    if not path.is_file() or "/" in name or ".." in name:
        raise FileNotFoundError(name)
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def available() -> list[str]:
    return sorted(p.stem for p in (config.FIXTURES_DIR / "scenarios").glob("*.jsonl"))


class Context:
    def __init__(self, db: Session, restaurant_id: str):
        self.db, self.rid = db, restaurant_id
        self.last_result: str | None = None

    @property
    def restaurant(self) -> Restaurant:
        r = self.db.get(Restaurant, self.rid)
        self.db.refresh(r)
        return r

    def table(self, label: str) -> Table:
        t = self.db.scalar(select(Table).where(Table.restaurant_id == self.rid, Table.label == label))
        if t is None:
            raise KeyError(f"no table {label}")
        self.db.refresh(t)
        return t

    def camera(self) -> Camera:
        c = self.db.scalar(select(Camera).where(Camera.restaurant_id == self.rid))
        self.db.refresh(c)
        return c

    def user(self, role: str | None) -> User | None:
        if not role:
            return None
        return self.db.scalar(select(User).join(Membership, Membership.user_id == User.id).where(
            Membership.restaurant_id == self.rid, Membership.role == role))

    def party(self, name: str) -> WaitlistParty:
        return self.db.scalar(select(WaitlistParty).where(
            WaitlistParty.restaurant_id == self.rid, WaitlistParty.name == name))


def apply_step(ctx: Context, step: dict, now: datetime) -> str | None:
    """Apply one step through the same service functions the HTTP API uses."""
    do, db, r = step["do"], ctx.db, ctx.restaurant
    result = None
    if do == "camera":
        observed = now + timedelta(seconds=step.get("observed_offset_s", 0))
        result = service.apply_camera_observation(
            db, r, ctx.camera(), ctx.table(step["table"]), step["occupied"], observed, now,
            event_id=step.get("event_id") or new_id("evt"))
    elif do == "heartbeat":
        zones = step.get("zones", "agree")
        tables = list(db.scalars(select(Table).where(Table.restaurant_id == ctx.rid)))
        if zones == "agree":
            payload = [{"table_id": t.id, "occupied": t.state == "occupied"} for t in tables]
        else:
            payload = [{"table_id": ctx.table(lbl).id, "occupied": occ} for lbl, occ in zones.items()]
        service.heartbeat(db, r, ctx.camera(), payload, now, now)
    elif do == "camera_offline":
        service.mark_camera_offline(db, ctx.camera())
    elif do == "camera_online":
        service.heartbeat(db, r, ctx.camera(), [], now, now)
    elif do == "staff":
        table = ctx.table(step["table"])
        version = table.version - 1 if step.get("stale_version") else table.version
        try:
            result = service.staff_command(db, r, table, step["command"], ctx.user(step.get("as")),
                                           now, expected_version=version)
        except service.Conflict:
            result = "conflict"
    elif do == "ack":
        table = ctx.table(step["table"])
        alert = db.scalar(select(Alert).where(Alert.table_id == table.id, Alert.status == "open"))
        result = service.acknowledge_alert(db, alert, ctx.user(step.get("as")), now) if alert else "none"
    elif do == "seat":
        try:
            result = service.seat_party(db, r, ctx.table(step["table"]), ctx.party(step["party"]),
                                        ctx.user(step.get("as")), now)
        except service.Conflict:
            result = "conflict"
    elif do == "add_party":
        db.add(WaitlistParty(restaurant_id=ctx.rid, name=step["name"], party_size=step["size"],
                             arrived_at=now))
        db.commit()
    elif do in ("note", "expect"):
        return ctx.last_result
    else:
        raise ValueError(f"unknown step kind: {do}")
    ctx.last_result = result
    return result


def check_expect(ctx: Context, step: dict, now: datetime) -> list[str]:
    """Returns a list of mismatches (empty when the expectation holds)."""
    errors, db = [], ctx.db
    floor = service.floor_snapshot(db, ctx.restaurant, now)
    if "last_result" in step and ctx.last_result != step["last_result"]:
        errors.append(f"last_result: expected {step['last_result']}, got {ctx.last_result}")
    if "camera_status" in step and floor["cameras"][0]["status"] != step["camera_status"]:
        errors.append(f"camera_status: expected {step['camera_status']}, got {floor['cameras'][0]['status']}")
    if "party_status" in step:
        for name, status in step["party_status"].items():
            got = ctx.party(name)
            db.refresh(got)
            if got.status != status:
                errors.append(f"party {name}: expected {status}, got {got.status}")
    if "table" in step:
        table = ctx.table(step["table"])
        tj = next(t for t in floor["tables"] if t["id"] == table.id)
        for key in ("state", "manual_hold"):
            if key in step and tj[key] != step[key]:
                errors.append(f"{step['table']}.{key}: expected {step[key]}, got {tj[key]}")
        alerts = [a for a in floor["alerts"] if a["table_id"] == table.id]
        if "open_alerts" in step and len(alerts) != step["open_alerts"]:
            errors.append(f"{step['table']} unresolved alerts: expected {step['open_alerts']}, got {len(alerts)}")
        if "alert_status" in step and (not alerts or alerts[0]["status"] != step["alert_status"]):
            errors.append(f"{step['table']} alert_status: expected {step['alert_status']}")
        if "suggestion" in step:
            sug = next((s for s in floor["suggestions"] if s["table_id"] == table.id), None)
            name = None
            if sug:
                name = next(p["name"] for p in floor["waitlist"] if p["id"] == sug["party_id"])
            if name != step["suggestion"]:
                errors.append(f"{step['table']} suggestion: expected {step['suggestion']}, got {name}")
    return errors


def run_sync(db: Session, restaurant_id: str, steps: list[dict], start: datetime) -> list[str]:
    """Run a whole scenario instantly on a simulated clock. Returns all expectation failures."""
    ctx, failures = Context(db, restaurant_id), []
    for i, step in enumerate(steps):
        now = start + timedelta(seconds=step.get("t", 0))
        if step["do"] == "expect":
            failures += [f"step {i + 1}: {e}" for e in check_expect(ctx, step, now)]
        else:
            apply_step(ctx, step, now)
    return failures
