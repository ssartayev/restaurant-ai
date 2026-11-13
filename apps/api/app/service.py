"""Domain operations: the only place that changes table state, alerts and the waitlist.

Every function takes `now` so tests can control time. Each function commits its own
transaction and publishes stream events only after the commit succeeded.
"""
from datetime import datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import bus, config
from .models import (NEEDS_CLEARING, OCCUPIED, READY, Alert, Camera, Membership, Restaurant, Table,
                     TableEvent, User, WaitlistParty, Zone)
from .state_machine import STAFF_TARGETS, TableSnapshot, decide_camera, decide_staff
from .util import iso, utcnow


class Conflict(Exception):
    """The table changed since the client last saw it (HTTP 409)."""


class Invalid(Exception):
    """The request cannot be applied (HTTP 422)."""


# ---------------------------------------------------------------- helpers

def snapshot_of(t: Table) -> TableSnapshot:
    return TableSnapshot(t.state, t.manual_hold, t.manual_hold_since, t.last_camera_observed_at)


def _write_table(db: Session, table: Table, values: dict, bump: bool) -> bool:
    """Optimistic write: succeeds only if nobody changed the row since we read it."""
    if bump:
        values = {**values, "version": table.version + 1}
    res = db.execute(
        update(Table).where(Table.id == table.id, Table.version == table.version).values(**values))
    if res.rowcount != 1:
        db.rollback()
        db.refresh(table)
        return False
    for k, v in values.items():
        setattr(table, k, v)
    return True


def _open_alert(db: Session, table: Table, type_: str, now: datetime) -> Alert | None:
    """Create an alert unless an unresolved one exists (duplicate suppression)."""
    existing = db.scalar(select(Alert).where(
        Alert.table_id == table.id, Alert.type == type_, Alert.status != "resolved"))
    if existing:
        return None
    alert = Alert(restaurant_id=table.restaurant_id, table_id=table.id, type=type_, created_at=now)
    try:
        with db.begin_nested():  # the unique partial index is the final guard against races
            db.add(alert)
            db.flush()
    except IntegrityError:
        return None
    return alert


def _resolve_alerts(db: Session, table: Table, now: datetime, type_: str | None = None):
    q = update(Alert).where(Alert.table_id == table.id, Alert.status != "resolved")
    if type_:
        q = q.where(Alert.type == type_)
    db.execute(q.values(status="resolved", resolved_at=now))


def _enter_state(db: Session, table: Table, new_state: str, now: datetime) -> tuple[dict, list]:
    """Side effects of entering a state. Returns extra column values and stream events."""
    values: dict = {"camera_presence_since": None}
    events: list = []
    if new_state == OCCUPIED:
        _resolve_alerts(db, table, now, "needs_clearing")
        values["greeted_at"] = None
    elif new_state == NEEDS_CLEARING:
        _resolve_alerts(db, table, now, "greet_reminder")
        alert = _open_alert(db, table, "needs_clearing", now)
        if alert:
            events.append(("alert.created", {"alert_id": alert.id, "table_id": table.id,
                                             "type": "needs_clearing", "label": table.label}))
    elif new_state == READY:
        _resolve_alerts(db, table, now)
        values["greeted_at"] = None
        values["current_party_id"] = None
    return values, events


def _publish(restaurant_id: str, events: list):
    for name, data in events:
        bus.publish(restaurant_id, name, data)


# ---------------------------------------------------------------- camera path

def apply_camera_observation(
    db: Session, restaurant: Restaurant, camera: Camera, table: Table, occupied: bool,
    observed_at: datetime, now: datetime, *, event_id: str | None = None,
    record_ignored: bool = True, payload_meta: dict | None = None,
) -> str:
    """Apply one camera observation to one table. Returns the result string of the ingest API.

    Idempotent (event_id), order-safe (observed_at), and safe against concurrent staff
    updates (optimistic version check with retry).
    """
    if event_id and db.scalar(select(TableEvent.id).where(
            TableEvent.restaurant_id == restaurant.id, TableEvent.camera_event_id == event_id)):
        return "duplicate"
    observed_at = min(observed_at, now)  # a device clock running ahead must not poison ordering

    for _ in range(4):
        decision = decide_camera(
            snapshot_of(table), occupied, observed_at, now,
            automation_enabled=restaurant.automation_enabled,
            camera_online=camera.status == "online",
            stale_after_s=config.STALE_EVENT_S,
        )
        from_state = table.state
        values: dict = {}
        stream: list = []
        if decision.accepted:
            values["last_camera_observed_at"] = observed_at
            # Presence at a table that needs clearing: remember since when, for the UI hint.
            if decision.new_state == NEEDS_CLEARING and not decision.changed:
                if occupied and table.camera_presence_since is None:
                    values["camera_presence_since"] = observed_at
                elif not occupied:
                    values["camera_presence_since"] = None
        if decision.release_hold:
            values.update(manual_hold=False, manual_hold_since=None)
        if decision.changed:
            extra, stream = _enter_state(db, table, decision.new_state, now)
            values.update(extra, state=decision.new_state, state_since=observed_at)
        bump = decision.changed or decision.release_hold
        if values and not _write_table(db, table, values, bump):
            continue  # a staff member changed the table meanwhile: decide again on fresh data
        break
    else:
        return "rejected"

    if event_id or record_ignored or decision.changed or decision.release_hold:
        db.add(TableEvent(
            restaurant_id=restaurant.id, table_id=table.id, source="camera",
            type="occupancy.changed" if event_id else "heartbeat.snapshot",
            from_state=from_state, to_state=decision.new_state if decision.changed else None,
            applied=decision.changed, reason=None if decision.changed else decision.result,
            camera_event_id=event_id, observed_at=observed_at, received_at=now,
            actor_name=f"camera:{camera.name}" + (" occupied" if occupied else " vacant")))
    try:
        db.commit()
    except IntegrityError:  # the same event_id was stored by a concurrent request
        db.rollback()
        db.refresh(table)
        return "duplicate"
    if decision.changed or decision.release_hold or "camera_presence_since" in values:
        _publish(restaurant.id, [("table.updated", {"table_id": table.id}), *stream])
    return decision.result


def heartbeat(db: Session, restaurant: Restaurant, camera: Camera, zones: list[dict],
              sent_at: datetime, now: datetime, health: str = "ok",
              health_reason: str | None = None) -> dict:
    """Record a heartbeat and reconcile with its occupancy snapshot.

    A camera returning from an outage puts all its tables on hold first, so a
    reconnect never flips a table by itself; the snapshot then releases the hold on
    every table where the camera agrees with the floor.
    """
    was_offline = camera.status != "online"
    changed = was_offline or camera.health != health
    camera.status, camera.last_heartbeat_at = "online", now
    camera.health, camera.health_reason = health, health_reason
    if was_offline:
        covered = select(Zone.table_id).where(Zone.camera_id == camera.id)
        db.execute(update(Table).where(Table.restaurant_id == restaurant.id, Table.id.in_(covered))
                   .values(manual_hold=True, manual_hold_since=None, version=Table.version + 1))
    db.commit()
    if changed:
        bus.publish(restaurant.id, "camera.status", {"camera_id": camera.id, "status": "online"})
    results = {}
    sent_at = min(sent_at, now)
    for z in zones:
        table = db.scalar(select(Table).where(
            Table.id == z["table_id"], Table.restaurant_id == restaurant.id))
        if table is None:
            results[z["table_id"]] = "rejected"
            continue
        db.refresh(table)
        results[table.id] = apply_camera_observation(
            db, restaurant, camera, table, bool(z["occupied"]), sent_at, now, record_ignored=False)
    return results


def mark_camera_offline(db: Session, camera: Camera):
    if camera.status == "offline":
        return
    camera.status = "offline"
    db.commit()
    bus.publish(camera.restaurant_id, "camera.status", {"camera_id": camera.id, "status": "offline"})


# ---------------------------------------------------------------- staff path

def staff_command(
    db: Session, restaurant: Restaurant, table: Table, command: str, user: User | None,
    now: datetime, *, expected_version: int | None = None, party: WaitlistParty | None = None,
) -> str:
    """Apply a staff command. Returns "applied" or "no_change"; raises Conflict on a stale version."""
    actor_id, actor_name = (user.id, user.name) if user else (None, "system")

    if command == "mark_greeted":
        if table.state != OCCUPIED:
            raise Invalid("only an occupied table can be marked greeted")
        if table.greeted_at is not None:
            return "no_change"
        table.greeted_at = now
        _resolve_alerts(db, table, now, "greet_reminder")
        db.add(TableEvent(restaurant_id=restaurant.id, table_id=table.id, source="staff",
                          type="mark_greeted", actor_user_id=actor_id, actor_name=actor_name,
                          observed_at=now, received_at=now))
        db.commit()
        bus.publish(restaurant.id, "table.updated", {"table_id": table.id})
        return "applied"

    decision = decide_staff(snapshot_of(table), command)
    if decision.result == "no_change":
        return "no_change"  # already in the target state: idempotent, no duplicate event
    if expected_version is not None and expected_version != table.version:
        raise Conflict()

    from_state = table.state
    stream: list = []
    if command == "resume_camera":
        values = {"manual_hold": False, "manual_hold_since": None}
    else:
        values, stream = _enter_state(db, table, decision.new_state, now)
        values.update(state=decision.new_state, state_since=now,
                      manual_hold=True, manual_hold_since=now)
        if party is not None:
            values["current_party_id"] = party.id
    if not _write_table(db, table, values, bump=True):
        # Someone else won the race. Same target reached -> fine; otherwise report a conflict.
        if command in STAFF_TARGETS and table.state == STAFF_TARGETS[command]:
            return "no_change"
        raise Conflict()
    if party is not None:
        party.status, party.seated_table_id = "seated", table.id
        party.seated_at = party.closed_at = now
    db.add(TableEvent(
        restaurant_id=restaurant.id, table_id=table.id, source="staff", type=command,
        from_state=from_state, to_state=decision.new_state if decision.changed and command != "resume_camera" else None,
        actor_user_id=actor_id, actor_name=actor_name, observed_at=now, received_at=now))
    db.commit()
    events = [("table.updated", {"table_id": table.id}), *stream]
    if party is not None or decision.new_state == READY:
        events.append(("waitlist.updated", {}))
    _publish(restaurant.id, events)
    return "applied"


def seat_party(db: Session, restaurant: Restaurant, table: Table, party: WaitlistParty,
               user: User | None, now: datetime, expected_version: int | None = None) -> str:
    """Host confirms seating: table -> occupied and party -> seated in ONE transaction."""
    if party.status not in ("waiting", "notified"):
        raise Invalid("party is not waiting")
    if table.state != READY:
        raise Conflict()
    return staff_command(db, restaurant, table, "mark_occupied", user, now,
                         expected_version=expected_version, party=party)


def acknowledge_alert(db: Session, alert: Alert, user: User | None, now: datetime) -> str:
    if alert.status != "open":
        return "no_change"
    alert.status, alert.acknowledged_at = "acknowledged", now
    alert.acknowledged_by = user.name if user else "system"
    db.commit()
    bus.publish(alert.restaurant_id, "alert.updated", {"alert_id": alert.id})
    return "applied"


# ---------------------------------------------------------------- waitlist

def suggest_seating(tables: list[Table], parties: list[WaitlistParty]) -> dict[str, str]:
    """Next eligible party for each Ready table. Returns {table_id: party_id}.

    Rule: take Ready tables smallest first; give each the party that has waited longest
    among those that fit (min_party <= size <= capacity) and are not already matched.
    Small tables are filled first so a couple is not sent to a six-top while a
    two-top is free. Nothing is seated automatically: the host confirms.
    """
    waiting = sorted((p for p in parties if p.status in ("waiting", "notified")),
                     key=lambda p: (p.arrived_at, p.id))
    taken: set[str] = set()
    out: dict[str, str] = {}
    for t in sorted((t for t in tables if t.state == READY), key=lambda t: (t.capacity, len(t.label), t.label)):
        for p in waiting:
            if p.id not in taken and t.min_party <= p.party_size <= t.capacity:
                out[t.id] = p.id
                taken.add(p.id)
                break
    return out


# ---------------------------------------------------------------- read models

def table_json(t: Table, now: datetime) -> dict:
    hint = (t.state == NEEDS_CLEARING and t.camera_presence_since is not None
            and (now - t.camera_presence_since).total_seconds() >= config.PRESENCE_HINT_S)
    return {
        "id": t.id, "label": t.label, "capacity": t.capacity, "min_party": t.min_party,
        "x": t.x, "y": t.y, "state": t.state, "state_since": iso(t.state_since),
        "version": t.version, "manual_hold": t.manual_hold, "greeted_at": iso(t.greeted_at),
        "current_party_id": t.current_party_id, "guests_seated_hint": hint,
    }


def alert_json(a: Alert) -> dict:
    return {"id": a.id, "table_id": a.table_id, "type": a.type, "status": a.status,
            "created_at": iso(a.created_at), "acknowledged_by": a.acknowledged_by,
            "acknowledged_at": iso(a.acknowledged_at), "renotified_at": iso(a.renotified_at)}


def party_json(p: WaitlistParty) -> dict:
    return {"id": p.id, "name": p.name, "party_size": p.party_size, "phone": p.phone,
            "arrived_at": iso(p.arrived_at), "status": p.status,
            "seated_table_id": p.seated_table_id, "seated_at": iso(p.seated_at)}


def camera_json(c: Camera) -> dict:
    return {"id": c.id, "name": c.name, "status": c.status, "health": c.health,
            "health_reason": c.health_reason, "last_heartbeat_at": iso(c.last_heartbeat_at),
            "config_version": c.config_version}


def floor_snapshot(db: Session, restaurant: Restaurant, now: datetime) -> dict:
    rid = restaurant.id
    tables = list(db.scalars(select(Table).where(Table.restaurant_id == rid).order_by(Table.label)))
    tables.sort(key=lambda t: (len(t.label), t.label))
    parties = list(db.scalars(select(WaitlistParty).where(
        WaitlistParty.restaurant_id == rid, WaitlistParty.status.in_(("waiting", "notified")))
        .order_by(WaitlistParty.arrived_at)))
    alerts = list(db.scalars(select(Alert).where(
        Alert.restaurant_id == rid, Alert.status != "resolved").order_by(Alert.created_at)))
    cameras = list(db.scalars(select(Camera).where(Camera.restaurant_id == rid)))
    suggestions = suggest_seating(tables, parties)
    return {
        "restaurant": {"id": rid, "name": restaurant.name, "timezone": restaurant.timezone,
                       "automation_enabled": restaurant.automation_enabled,
                       "is_demo": restaurant.is_demo, "settings": restaurant.settings or {}},
        "server_time": iso(now),
        "tables": [table_json(t, now) for t in tables],
        "alerts": [alert_json(a) for a in alerts],
        "waitlist": [party_json(p) for p in parties],
        "suggestions": [{"table_id": t, "party_id": p} for t, p in suggestions.items()],
        "cameras": [camera_json(c) for c in cameras],
    }


# ---------------------------------------------------------------- periodic sweep

def sweep(db: Session, now: datetime | None = None) -> dict:
    """Time-driven rules. Called every few seconds by a background task; safe to call any time."""
    now = now or utcnow()
    out = {"offline": 0, "greet": 0, "renotify": 0, "scrubbed": 0, "expired": 0}

    # 1. Camera offline: no heartbeat for HEARTBEAT_TIMEOUT_S. Demo cameras are driven by the runner.
    cutoff = now - timedelta(seconds=config.HEARTBEAT_TIMEOUT_S)
    for cam in db.scalars(select(Camera).join(Restaurant, Restaurant.id == Camera.restaurant_id).where(
            Camera.status == "online", Restaurant.is_demo.is_(False),
            (Camera.last_heartbeat_at.is_(None)) | (Camera.last_heartbeat_at < cutoff))):
        mark_camera_offline(db, cam)
        out["offline"] += 1

    # 2. Greeted reminders (opt-in per restaurant: settings.greet_reminders).
    greet_cutoff = now - timedelta(seconds=config.GREET_REMINDER_S)
    for t in db.scalars(select(Table).where(
            Table.state == OCCUPIED, Table.greeted_at.is_(None), Table.state_since < greet_cutoff)):
        r = db.get(Restaurant, t.restaurant_id)
        if not (r.settings or {}).get("greet_reminders"):
            continue
        alert = _open_alert(db, t, "greet_reminder", now)
        db.commit()
        if alert:
            out["greet"] += 1
            bus.publish(r.id, "alert.created", {"alert_id": alert.id, "table_id": t.id,
                                                "type": "greet_reminder", "label": t.label})

    # 3. Re-notify ONCE for clearing alerts nobody acknowledged. Same alert row, never a second one.
    for a in db.scalars(select(Alert).where(
            Alert.type == "needs_clearing", Alert.status == "open", Alert.renotified_at.is_(None),
            Alert.created_at < now - timedelta(seconds=config.RENOTIFY_S))):
        a.renotified_at = now
        db.commit()
        out["renotify"] += 1
        bus.publish(a.restaurant_id, "alert.renotify", {"alert_id": a.id, "table_id": a.table_id})

    # 4. Retention: scrub guest name/phone, drop old events, delete expired demo sandboxes.
    pii_cutoff = now - timedelta(hours=config.WAITLIST_PII_HOURS)
    res = db.execute(update(WaitlistParty).where(
        WaitlistParty.closed_at.is_not(None), WaitlistParty.closed_at < pii_cutoff,
        (WaitlistParty.name.is_not(None)) | (WaitlistParty.phone.is_not(None)))
        .values(name=None, phone=None))
    out["scrubbed"] = res.rowcount
    db.execute(delete(TableEvent).where(
        TableEvent.observed_at < now - timedelta(days=config.EVENT_RETENTION_DAYS)))
    db.commit()
    for r in db.scalars(select(Restaurant).where(
            Restaurant.expires_at.is_not(None), Restaurant.expires_at < now)):
        delete_restaurant(db, r.id)
        out["expired"] += 1
    return out


def delete_restaurant(db: Session, restaurant_id: str):
    """Remove a restaurant and everything it owns, including accounts that belong only to it."""
    user_ids = list(db.scalars(select(Membership.user_id).where(
        Membership.restaurant_id == restaurant_id)))
    db.execute(delete(Restaurant).where(Restaurant.id == restaurant_id))  # FK cascades do the rest
    db.flush()
    for uid in user_ids:
        if not db.scalar(select(Membership.user_id).where(Membership.user_id == uid)):
            db.execute(delete(User).where(User.id == uid))
    db.commit()
