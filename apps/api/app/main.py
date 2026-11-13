"""HTTP API. Routes are thin: they authenticate, scope to a restaurant, and call service.py.

Tenant rule: every route under /v1/restaurants/{rid} goes through `member()`, which
returns 404 unless the signed-in user has a membership in that restaurant. Edge routes
derive the restaurant from the device token and never trust IDs in the body.
"""
import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import analytics, bus, config, demo, scenario, security, service
from . import seed as seed_mod
from .db import SessionLocal, get_db, init_db
from .models import (ROLES, Alert, AuthSession, Camera, DemoRate, Membership, Restaurant, Table,
                     TableEvent, User, WaitlistParty, Zone)
from .state_machine import STAFF_COMMANDS
from .util import iso, to_naive_utc, utcnow

COOKIE = "session"


# ------------------------------------------------------------------ lifecycle

async def _sweep_loop():
    while True:
        await asyncio.sleep(config.SWEEP_INTERVAL_S)
        try:
            def run():
                with SessionLocal() as db:
                    service.sweep(db)
            await asyncio.to_thread(run)
        except Exception as exc:  # keep the loop alive; the next tick retries
            print("sweep failed:", repr(exc))


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    bus.bind_loop(asyncio.get_running_loop())
    if os.environ.get("SEED_DEV", "1") == "1":
        with SessionLocal() as db:
            seed_mod.ensure_dev_restaurant(db)
    task = asyncio.create_task(_sweep_loop()) if os.environ.get("SWEEP", "1") == "1" else None
    yield
    if task:
        task.cancel()


app = FastAPI(title="Restaurant Table Management API", version="1.0.0", lifespan=lifespan)


@app.exception_handler(service.Invalid)
async def _invalid(_, exc: service.Invalid):
    from fastapi.responses import JSONResponse
    return JSONResponse({"detail": str(exc)}, status_code=422)


# ------------------------------------------------------------------ auth

class Ctx:
    def __init__(self, user: User, restaurant: Restaurant, role: str):
        self.user, self.restaurant, self.role = user, restaurant, role


def _user_from_cookie(request: Request, db: Session) -> User:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "not signed in")
    sess = db.get(AuthSession, security.token_hash(token))
    if sess is None or sess.expires_at < utcnow():
        raise HTTPException(401, "session expired")
    user = db.get(User, sess.user_id)
    if user is None or not user.active:
        raise HTTPException(401, "account inactive")
    return user


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    return _user_from_cookie(request, db)


def _authorize(db: Session, user: User, rid: str, min_role: str) -> Ctx:
    m = db.get(Membership, (user.id, rid))
    restaurant = db.get(Restaurant, rid) if m else None
    if m is None or restaurant is None:
        raise HTTPException(404, "not found")  # 404, not 403: do not reveal that the ID exists
    if ROLES.index(m.role) < ROLES.index(min_role):
        raise HTTPException(403, f"requires role {min_role}")
    return Ctx(user, restaurant, m.role)


def member(min_role: str = "staff"):
    def dep(rid: str, user: User = Depends(current_user), db: Session = Depends(get_db)) -> Ctx:
        return _authorize(db, user, rid, min_role)
    return dep


def device(request: Request, db: Session = Depends(get_db)) -> Camera:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(401, "device token required")
    cam = db.scalar(select(Camera).where(Camera.token_hash == security.token_hash(header[7:].strip())))
    if cam is None:
        raise HTTPException(401, "unknown device token")
    return cam


def _start_session(db: Session, response: Response, user: User):
    token = security.new_token()
    db.add(AuthSession(token_hash=security.token_hash(token), user_id=user.id,
                       expires_at=utcnow() + timedelta(hours=config.SESSION_HOURS)))
    db.commit()
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax", secure=config.COOKIE_SECURE,
                        max_age=config.SESSION_HOURS * 3600, path="/")


def _table(db: Session, rid: str, tid: str) -> Table:
    t = db.scalar(select(Table).where(Table.id == tid, Table.restaurant_id == rid))
    if t is None:
        raise HTTPException(404, "not found")
    return t


# ------------------------------------------------------------------ schemas

class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginIn(Strict):
    email: str
    password: str


class CommandIn(Strict):
    command: Literal[STAFF_COMMANDS]  # type: ignore[valid-type]
    expected_version: int | None = None
    reason: str | None = Field(None, max_length=200)


class SeatIn(Strict):
    party_id: str
    expected_version: int | None = None


class PartyIn(Strict):
    name: str = Field(min_length=1, max_length=100)
    party_size: int = Field(ge=1, le=40)
    phone: str | None = Field(None, max_length=40)


class PartyPatch(Strict):
    status: Literal["waiting", "notified", "cancelled", "no_show"] | None = None
    party_size: int | None = Field(None, ge=1, le=40)
    name: str | None = Field(None, min_length=1, max_length=100)


class TableIn(Strict):
    label: str = Field(min_length=1, max_length=32)
    capacity: int = Field(ge=1, le=40)
    min_party: int = Field(1, ge=1, le=40)
    x: float = Field(0.5, ge=0, le=1)
    y: float = Field(0.5, ge=0, le=1)


class TablePatch(Strict):
    label: str | None = Field(None, min_length=1, max_length=32)
    capacity: int | None = Field(None, ge=1, le=40)
    min_party: int | None = Field(None, ge=1, le=40)
    x: float | None = Field(None, ge=0, le=1)
    y: float | None = Field(None, ge=0, le=1)


class ZoneIn(Strict):
    camera_id: str
    polygons: list[list[tuple[float, float]]]


class CameraIn(Strict):
    name: str = Field(min_length=1, max_length=100)


class MemberIn(Strict):
    email: str = Field(min_length=3, max_length=320)
    name: str = Field(min_length=1, max_length=200)
    role: Literal["staff", "host", "admin"]
    password: str = Field(min_length=8, max_length=200)


class MemberPatch(Strict):
    role: Literal["staff", "host", "admin"] | None = None
    active: bool | None = None


class SettingsPatch(Strict):
    name: str | None = Field(None, min_length=1, max_length=200)
    timezone: str | None = None
    automation_enabled: bool | None = None
    greet_reminders: bool | None = None


class OccupancyEvent(Strict):
    """Mirrors packages/contracts/events/occupancy-changed.v1.schema.json. Extra fields are rejected."""
    schema_version: Literal[1]
    event_id: str = Field(min_length=8, max_length=64)
    type: Literal["occupancy.changed"]
    restaurant_id: str | None = None
    camera_id: str | None = None
    table_id: str
    occupied: bool
    person_count: int | None = Field(None, ge=0)
    confidence: float | None = Field(None, ge=0, le=1)
    observed_at: datetime
    window_s: float | None = Field(None, ge=0)
    sequence: int | None = Field(None, ge=0)
    worker_version: str | None = None
    config_version: int | None = Field(None, ge=0)


class EventsIn(Strict):
    events: list[OccupancyEvent] = Field(max_length=500)


class ZoneState(Strict):
    table_id: str
    occupied: bool
    since: datetime | None = None


class HeartbeatIn(Strict):
    schema_version: Literal[1]
    type: Literal["camera.heartbeat"]
    camera_id: str | None = None
    sequence: int | None = Field(None, ge=0)
    sent_at: datetime
    health: Literal["ok", "degraded"] = "ok"
    health_reason: str | None = Field(None, max_length=200)
    worker_version: str | None = None
    zones: list[ZoneState] = Field(default_factory=list, max_length=500)


class DemoScenarioIn(Strict):
    action: Literal["start", "pause", "resume", "stop", "reset"]
    scenario: str = "demo_dinner"
    speed: float = Field(1.0, ge=0.25, le=20)


class DemoRoleIn(Strict):
    role: Literal["staff", "host", "admin"]


# ------------------------------------------------------------------ session routes

@app.get("/healthz")
def healthz():
    return {"status": "ok", "git_sha": config.GIT_SHA}


@app.post("/v1/auth/login")
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if user is None or not user.active or not security.verify_password(body.password, user.password_hash):
        raise HTTPException(401, "wrong email or password")
    _start_session(db, response, user)
    return {"ok": True}


@app.post("/v1/auth/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(COOKIE)
    if token:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == security.token_hash(token)))
        db.commit()
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@app.get("/v1/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.execute(select(Membership, Restaurant).join(
        Restaurant, Restaurant.id == Membership.restaurant_id).where(Membership.user_id == user.id))
    return {"id": user.id, "email": user.email, "name": user.name,
            "memberships": [{"restaurant_id": r.id, "restaurant_name": r.name, "role": m.role,
                             "is_demo": r.is_demo} for m, r in rows]}


# ------------------------------------------------------------------ floor, commands, stream

@app.get("/v1/restaurants/{rid}/floor")
def get_floor(ctx: Ctx = Depends(member()), db: Session = Depends(get_db)):
    out = service.floor_snapshot(db, ctx.restaurant, utcnow())
    out["role"] = ctx.role
    out["demo"] = demo.status(ctx.restaurant.id) if ctx.restaurant.is_demo else None
    return out


@app.post("/v1/restaurants/{rid}/tables/{tid}/commands")
def table_command(tid: str, body: CommandIn, ctx: Ctx = Depends(member()),
                  db: Session = Depends(get_db)):
    table = _table(db, ctx.restaurant.id, tid)
    now = utcnow()
    try:
        result = service.staff_command(db, ctx.restaurant, table, body.command, ctx.user, now,
                                       expected_version=body.expected_version)
    except service.Conflict:
        db.refresh(table)
        last = db.scalar(select(TableEvent).where(
            TableEvent.table_id == table.id, TableEvent.applied.is_(True),
            TableEvent.source == "staff")
            .order_by(TableEvent.received_at.desc()))
        raise HTTPException(409, {"message": "table changed", "table": service.table_json(table, now),
                                  "changed_by": last.actor_name if last else None})
    return {"result": result, "table": service.table_json(table, now)}


@app.post("/v1/restaurants/{rid}/tables/{tid}/seat")
def seat(tid: str, body: SeatIn, ctx: Ctx = Depends(member("host")), db: Session = Depends(get_db)):
    table = _table(db, ctx.restaurant.id, tid)
    party = db.scalar(select(WaitlistParty).where(
        WaitlistParty.id == body.party_id, WaitlistParty.restaurant_id == ctx.restaurant.id))
    if party is None:
        raise HTTPException(404, "not found")
    now = utcnow()
    try:
        service.seat_party(db, ctx.restaurant, table, party, ctx.user, now, body.expected_version)
    except service.Conflict:
        db.refresh(table)
        raise HTTPException(409, {"message": "table changed", "table": service.table_json(table, now)})
    return {"result": "applied", "table": service.table_json(table, now),
            "party": service.party_json(party)}


@app.get("/v1/restaurants/{rid}/stream")
async def stream(rid: str, request: Request):
    """Server-Sent Events. Clients refetch the floor snapshot on every event and on reconnect."""
    def check():
        with SessionLocal() as db:  # short-lived: do not hold a connection for the stream's life
            _authorize(db, _user_from_cookie(request, db), rid, "staff")
    await asyncio.to_thread(check)
    queue = bus.subscribe(rid)

    async def gen():
        try:
            yield "event: hello\ndata: {}\n\n"
            while True:
                try:
                    yield await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                if await request.is_disconnected():
                    break
        finally:
            bus.unsubscribe(rid, queue)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------ alerts

@app.get("/v1/restaurants/{rid}/alerts")
def list_alerts(status: str | None = None, ctx: Ctx = Depends(member()),
                db: Session = Depends(get_db)):
    q = select(Alert).where(Alert.restaurant_id == ctx.restaurant.id).order_by(Alert.created_at.desc())
    q = q.where(Alert.status == status) if status else q.where(Alert.status != "resolved")
    return [service.alert_json(a) for a in db.scalars(q.limit(200))]


@app.post("/v1/restaurants/{rid}/alerts/{aid}/ack")
def ack_alert(aid: str, ctx: Ctx = Depends(member()), db: Session = Depends(get_db)):
    alert = db.scalar(select(Alert).where(Alert.id == aid, Alert.restaurant_id == ctx.restaurant.id))
    if alert is None:
        raise HTTPException(404, "not found")
    result = service.acknowledge_alert(db, alert, ctx.user, utcnow())
    return {"result": result, "alert": service.alert_json(alert)}


# ------------------------------------------------------------------ waitlist

@app.get("/v1/restaurants/{rid}/waitlist")
def list_waitlist(ctx: Ctx = Depends(member()), db: Session = Depends(get_db)):
    return [service.party_json(p) for p in db.scalars(select(WaitlistParty).where(
        WaitlistParty.restaurant_id == ctx.restaurant.id,
        WaitlistParty.status.in_(("waiting", "notified"))).order_by(WaitlistParty.arrived_at))]


@app.post("/v1/restaurants/{rid}/waitlist", status_code=201)
def add_party(body: PartyIn, ctx: Ctx = Depends(member("host")), db: Session = Depends(get_db)):
    party = WaitlistParty(restaurant_id=ctx.restaurant.id, name=body.name.strip(),
                          party_size=body.party_size, phone=body.phone, arrived_at=utcnow())
    db.add(party)
    db.commit()
    bus.publish(ctx.restaurant.id, "waitlist.updated", {})
    return service.party_json(party)


@app.patch("/v1/restaurants/{rid}/waitlist/{pid}")
def patch_party(pid: str, body: PartyPatch, ctx: Ctx = Depends(member("host")),
                db: Session = Depends(get_db)):
    party = db.scalar(select(WaitlistParty).where(
        WaitlistParty.id == pid, WaitlistParty.restaurant_id == ctx.restaurant.id))
    if party is None:
        raise HTTPException(404, "not found")
    if party.status == "seated":
        raise HTTPException(422, "party is already seated")
    if body.name is not None:
        party.name = body.name
    if body.party_size is not None:
        party.party_size = body.party_size
    if body.status is not None:
        party.status = body.status
        party.closed_at = utcnow() if body.status in ("cancelled", "no_show") else None
    db.commit()
    bus.publish(ctx.restaurant.id, "waitlist.updated", {})
    return service.party_json(party)


# ------------------------------------------------------------------ history and analytics

@app.get("/v1/restaurants/{rid}/tables/{tid}/events")
def table_events(tid: str, limit: int = 50, before: datetime | None = None,
                 ctx: Ctx = Depends(member()), db: Session = Depends(get_db)):
    table = _table(db, ctx.restaurant.id, tid)
    q = select(TableEvent).where(TableEvent.table_id == table.id)
    if before:
        q = q.where(TableEvent.observed_at < to_naive_utc(before))
    rows = db.scalars(q.order_by(TableEvent.observed_at.desc(), TableEvent.received_at.desc())
                      .limit(max(1, min(limit, 200))))
    return [{"id": e.id, "source": e.source, "type": e.type, "from_state": e.from_state,
             "to_state": e.to_state, "applied": e.applied, "reason": e.reason,
             "actor": e.actor_name, "observed_at": iso(e.observed_at)} for e in rows]


def _range(from_: datetime | None, to: datetime | None, default_days: int):
    now = utcnow()
    end = to_naive_utc(to) if to else now
    start = to_naive_utc(from_) if from_ else end - timedelta(days=default_days)
    if start >= end:
        raise HTTPException(422, "from must be before to")
    return start, end, now


@app.get("/v1/restaurants/{rid}/analytics/summary")
def analytics_summary(from_: datetime | None = Query(None, alias="from"), to: datetime | None = None,
                      ctx: Ctx = Depends(member("admin")), db: Session = Depends(get_db)):
    start, end, now = _range(from_, to, 1)
    return analytics.summary(db, ctx.restaurant.id, start, end, now)


@app.get("/v1/restaurants/{rid}/analytics/peak-hours")
def analytics_peak(from_: datetime | None = Query(None, alias="from"), to: datetime | None = None,
                   ctx: Ctx = Depends(member("admin")), db: Session = Depends(get_db)):
    start, end, _ = _range(from_, to, 28)
    return analytics.peak_hours(db, ctx.restaurant.id, ctx.restaurant.timezone, start, end)


# ------------------------------------------------------------------ setup (admin)

@app.patch("/v1/restaurants/{rid}/settings")
def patch_settings(body: SettingsPatch, ctx: Ctx = Depends(member("admin")),
                   db: Session = Depends(get_db)):
    r = ctx.restaurant
    if body.name is not None:
        r.name = body.name
    if body.timezone is not None:
        from zoneinfo import ZoneInfo
        try:
            ZoneInfo(body.timezone)
        except Exception:
            raise HTTPException(422, "unknown timezone")
        r.timezone = body.timezone
    if body.automation_enabled is not None:
        r.automation_enabled = body.automation_enabled  # the kill switch: camera events stop applying
    if body.greet_reminders is not None:
        r.settings = {**(r.settings or {}), "greet_reminders": body.greet_reminders}
    db.commit()
    bus.publish(r.id, "settings.updated", {})
    return {"ok": True}


@app.post("/v1/restaurants/{rid}/tables", status_code=201)
def create_table(body: TableIn, ctx: Ctx = Depends(member("admin")), db: Session = Depends(get_db)):
    rid = ctx.restaurant.id
    if db.scalar(select(Table.id).where(Table.restaurant_id == rid, Table.label == body.label)):
        raise HTTPException(422, "a table with this label exists")
    t = Table(restaurant_id=rid, **body.model_dump())
    db.add(t)
    db.commit()
    bus.publish(rid, "table.updated", {"table_id": t.id})
    return service.table_json(t, utcnow())


@app.patch("/v1/restaurants/{rid}/tables/{tid}")
def patch_table(tid: str, body: TablePatch, ctx: Ctx = Depends(member("admin")),
                db: Session = Depends(get_db)):
    t = _table(db, ctx.restaurant.id, tid)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(t, k, v)
    db.commit()
    bus.publish(ctx.restaurant.id, "table.updated", {"table_id": t.id})
    return service.table_json(t, utcnow())


@app.delete("/v1/restaurants/{rid}/tables/{tid}")
def delete_table(tid: str, ctx: Ctx = Depends(member("admin")), db: Session = Depends(get_db)):
    t = _table(db, ctx.restaurant.id, tid)
    db.execute(delete(Table).where(Table.id == t.id))
    _bump_config(db, ctx.restaurant.id)
    db.commit()
    bus.publish(ctx.restaurant.id, "table.updated", {"table_id": tid})
    return {"ok": True}


def _bump_config(db: Session, rid: str):
    for cam in db.scalars(select(Camera).where(Camera.restaurant_id == rid)):
        cam.config_version += 1


@app.get("/v1/restaurants/{rid}/cameras")
def list_cameras(ctx: Ctx = Depends(member("admin")), db: Session = Depends(get_db)):
    return [service.camera_json(c) for c in db.scalars(
        select(Camera).where(Camera.restaurant_id == ctx.restaurant.id))]


@app.post("/v1/restaurants/{rid}/cameras", status_code=201)
def create_camera(body: CameraIn, ctx: Ctx = Depends(member("admin")), db: Session = Depends(get_db)):
    token = security.new_token()
    cam = Camera(restaurant_id=ctx.restaurant.id, name=body.name, token_hash=security.token_hash(token))
    db.add(cam)
    db.commit()
    # The device token is shown once and stored only as a hash.
    return {**service.camera_json(cam), "device_token": token}


@app.post("/v1/restaurants/{rid}/cameras/{cid}/rotate-token")
def rotate_token(cid: str, ctx: Ctx = Depends(member("admin")), db: Session = Depends(get_db)):
    cam = db.scalar(select(Camera).where(Camera.id == cid, Camera.restaurant_id == ctx.restaurant.id))
    if cam is None:
        raise HTTPException(404, "not found")
    token = security.new_token()
    cam.token_hash = security.token_hash(token)
    db.commit()
    return {**service.camera_json(cam), "device_token": token}


@app.get("/v1/restaurants/{rid}/zones")
def list_zones(ctx: Ctx = Depends(member("admin")), db: Session = Depends(get_db)):
    return [{"id": z.id, "camera_id": z.camera_id, "table_id": z.table_id, "polygons": z.polygons}
            for z in db.scalars(select(Zone).where(Zone.restaurant_id == ctx.restaurant.id))]


@app.put("/v1/restaurants/{rid}/tables/{tid}/zone")
def put_zone(tid: str, body: ZoneIn, ctx: Ctx = Depends(member("admin")),
             db: Session = Depends(get_db)):
    rid = ctx.restaurant.id
    table = _table(db, rid, tid)
    cam = db.scalar(select(Camera).where(Camera.id == body.camera_id, Camera.restaurant_id == rid))
    if cam is None:
        raise HTTPException(404, "not found")
    for poly in body.polygons:
        if len(poly) < 3 or any(not (0 <= x <= 1 and 0 <= y <= 1) for x, y in poly):
            raise HTTPException(422, "each polygon needs 3+ points with coordinates in 0..1")
    zone = db.scalar(select(Zone).where(Zone.camera_id == cam.id, Zone.table_id == table.id))
    polygons = [[list(p) for p in poly] for poly in body.polygons]
    if zone is None:
        db.add(Zone(restaurant_id=rid, camera_id=cam.id, table_id=table.id, polygons=polygons))
    else:
        zone.polygons = polygons
    cam.config_version += 1
    db.commit()
    return {"ok": True, "config_version": cam.config_version}


@app.get("/v1/restaurants/{rid}/members")
def list_members(ctx: Ctx = Depends(member("admin")), db: Session = Depends(get_db)):
    rows = db.execute(select(User, Membership).join(Membership, Membership.user_id == User.id)
                      .where(Membership.restaurant_id == ctx.restaurant.id).order_by(User.name))
    return [{"id": u.id, "email": u.email, "name": u.name, "role": m.role, "active": u.active}
            for u, m in rows]


@app.post("/v1/restaurants/{rid}/members", status_code=201)
def add_member(body: MemberIn, ctx: Ctx = Depends(member("admin")), db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    if db.scalar(select(User.id).where(User.email == email)):
        # Deliberately generic: do not reveal whether an account exists in another restaurant.
        raise HTTPException(422, "this email cannot be added")
    user = User(email=email, name=body.name, password_hash=security.hash_password(body.password))
    db.add(user)
    db.flush()
    db.add(Membership(user_id=user.id, restaurant_id=ctx.restaurant.id, role=body.role))
    db.commit()
    return {"id": user.id, "email": user.email, "name": user.name, "role": body.role, "active": True}


@app.patch("/v1/restaurants/{rid}/members/{uid}")
def patch_member(uid: str, body: MemberPatch, ctx: Ctx = Depends(member("admin")),
                 db: Session = Depends(get_db)):
    m = db.get(Membership, (uid, ctx.restaurant.id))
    if m is None:
        raise HTTPException(404, "not found")
    if uid == ctx.user.id:
        raise HTTPException(422, "you cannot change your own role or deactivate yourself")
    user = db.get(User, uid)
    if body.role is not None:
        m.role = body.role
    if body.active is not None:
        user.active = body.active
        if not body.active:
            db.execute(delete(AuthSession).where(AuthSession.user_id == uid))
    db.commit()
    return {"id": user.id, "email": user.email, "name": user.name, "role": m.role,
            "active": user.active}


@app.get("/v1/restaurants/{rid}/export")
def export_restaurant(ctx: Ctx = Depends(member("admin")), db: Session = Depends(get_db)):
    rid = ctx.restaurant.id
    events = db.scalars(select(TableEvent).where(TableEvent.restaurant_id == rid)
                        .order_by(TableEvent.observed_at))
    return {"restaurant": {"id": rid, "name": ctx.restaurant.name},
            "tables": [service.table_json(t, utcnow()) for t in db.scalars(
                select(Table).where(Table.restaurant_id == rid))],
            "events": [{"table_id": e.table_id, "source": e.source, "type": e.type,
                        "from_state": e.from_state, "to_state": e.to_state, "applied": e.applied,
                        "reason": e.reason, "observed_at": iso(e.observed_at)} for e in events]}


@app.delete("/v1/restaurants/{rid}")
def delete_restaurant(ctx: Ctx = Depends(member("admin")), db: Session = Depends(get_db)):
    """Offboarding: removes the restaurant and everything it owns."""
    demo.stop(ctx.restaurant.id)
    service.delete_restaurant(db, ctx.restaurant.id)
    return {"ok": True}


# ------------------------------------------------------------------ edge (device token)

@app.post("/v1/ingest/events")
def ingest_events(body: EventsIn, cam: Camera = Depends(device), db: Session = Depends(get_db)):
    restaurant = db.get(Restaurant, cam.restaurant_id)
    now = utcnow()
    results = []
    for ev in body.events:
        table = db.scalar(select(Table).where(
            Table.id == ev.table_id, Table.restaurant_id == restaurant.id))
        if table is None:  # includes table IDs of other restaurants
            results.append({"event_id": ev.event_id, "result": "rejected"})
            continue
        db.refresh(table)
        result = service.apply_camera_observation(
            db, restaurant, cam, table, ev.occupied, to_naive_utc(ev.observed_at), now,
            event_id=ev.event_id)
        results.append({"event_id": ev.event_id, "result": result})
    if body.events:
        seqs = [e.sequence for e in body.events if e.sequence is not None]
        if seqs:
            cam.last_sequence = max(cam.last_sequence, *seqs)
            db.commit()
    return {"results": results}


@app.post("/v1/ingest/heartbeat")
def ingest_heartbeat(body: HeartbeatIn, cam: Camera = Depends(device), db: Session = Depends(get_db)):
    restaurant = db.get(Restaurant, cam.restaurant_id)
    now = utcnow()
    results = service.heartbeat(db, restaurant, cam, [z.model_dump() for z in body.zones],
                                to_naive_utc(body.sent_at), now, body.health, body.health_reason)
    return {"status": "online", "config_version": cam.config_version, "results": results}


@app.get("/v1/worker/config")
def worker_config(cam: Camera = Depends(device), db: Session = Depends(get_db)):
    rows = db.execute(select(Zone, Table).join(Table, Table.id == Zone.table_id)
                      .where(Zone.camera_id == cam.id))
    return {"restaurant_id": cam.restaurant_id, "camera_id": cam.id,
            "config_version": cam.config_version, "thresholds": cam.thresholds or {},
            "zones": [{"table_id": t.id, "label": t.label, "polygons": z.polygons} for z, t in rows]}


# ------------------------------------------------------------------ demo

@app.post("/v1/demo/sessions", status_code=201)
def demo_create(request: Request, response: Response, db: Session = Depends(get_db)):
    ip = request.client.host if request.client else "unknown"
    hour_ago = utcnow() - timedelta(hours=1)
    db.execute(delete(DemoRate).where(DemoRate.created_at < hour_ago))
    recent = len(list(db.scalars(select(DemoRate.id).where(DemoRate.ip == ip))))
    if recent >= config.DEMO_MAX_PER_IP_PER_HOUR:
        raise HTTPException(429, "too many demo sessions; try again later")
    db.add(DemoRate(ip=ip))
    out = demo.create_sandbox(db)
    _start_session(db, response, out["users"]["admin"])
    return {"restaurant_id": out["restaurant"].id, "role": "admin"}


@app.post("/v1/restaurants/{rid}/demo/role")
def demo_role(body: DemoRoleIn, response: Response, ctx: Ctx = Depends(member()),
              db: Session = Depends(get_db)):
    """Demo only: continue as the sandbox's admin, host or staff account."""
    if not ctx.restaurant.is_demo:
        raise HTTPException(404, "not found")
    user = db.scalar(select(User).join(Membership, Membership.user_id == User.id).where(
        Membership.restaurant_id == ctx.restaurant.id, Membership.role == body.role))
    _start_session(db, response, user)
    return {"role": body.role}


@app.get("/v1/restaurants/{rid}/demo/scenarios")
def demo_scenarios(ctx: Ctx = Depends(member())):
    if not ctx.restaurant.is_demo:
        raise HTTPException(404, "not found")
    return [s for s in scenario.available() if s.startswith("demo_")]


def _demo_member(rid: str, request: Request) -> bool:
    """Auth for async routes: uses a short-lived session instead of a request-long one."""
    with SessionLocal() as db:
        return _authorize(db, _user_from_cookie(request, db), rid, "staff").restaurant.is_demo


@app.post("/v1/restaurants/{rid}/demo/scenario")
async def demo_scenario(rid: str, body: DemoScenarioIn, is_demo: bool = Depends(_demo_member)):
    if not is_demo:
        raise HTTPException(404, "not found")
    if body.action == "start":
        if not body.scenario.startswith("demo_") or body.scenario not in scenario.available():
            raise HTTPException(422, "unknown scenario")
        return demo.start(rid, body.scenario, body.speed)
    if body.action in ("pause", "resume"):
        return demo.pause(rid, body.action == "pause") or {}
    if body.action == "stop":
        demo.stop(rid)
        return {}
    demo.stop(rid)

    def reset():
        with SessionLocal() as db:
            demo.reset_sandbox(db, rid)
    await asyncio.to_thread(reset)
    return {"reset": True}


# ------------------------------------------------------------------ static web app

if config.WEB_DIST.is_dir():
    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("v1/"):
            raise HTTPException(404, "not found")
        target = (config.WEB_DIST / path).resolve()
        if path and target.is_file() and config.WEB_DIST.resolve() in target.parents:
            return FileResponse(target)
        return FileResponse(config.WEB_DIST / "index.html")
