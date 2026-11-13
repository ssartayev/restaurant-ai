"""Create a restaurant from fixtures/seed/*.json, with synthetic history. No real data."""
import json
import random
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config, security
from .models import (NEEDS_CLEARING, OCCUPIED, Alert, Camera, Membership, Organization, Restaurant,
                     Table, TableEvent, User, WaitlistParty, Zone)
from .util import new_id, utcnow


def load_seed(name: str = "demo_restaurant") -> dict:
    return json.loads((config.FIXTURES_DIR / "seed" / f"{name}.json").read_text())


def default_zone(x: float, y: float) -> list:
    """A rectangle around the table position, standing in for a hand-drawn seat zone."""
    w, h = 0.09, 0.11
    return [[[round(x - w, 3), round(y - h, 3)], [round(x + w, 3), round(y - h, 3)],
             [round(x + w, 3), round(y + h, 3)], [round(x - w, 3), round(y + h, 3)]]]


def create_restaurant(db: Session, seed: dict, now: datetime | None = None, *, is_demo: bool = False,
                      unique_emails: bool = False, with_history: bool = True) -> dict:
    """Returns {"restaurant", "users": {role: User}, "camera", "device_token", "tables": {label: Table}}."""
    now = now or utcnow()
    rng = random.Random(7)
    org = Organization(name=seed["name"])
    db.add(org)
    db.flush()
    r = Restaurant(organization_id=org.id, name=seed["name"], timezone=seed.get("timezone", "UTC"),
                   is_demo=is_demo, settings={},
                   expires_at=now + timedelta(hours=config.DEMO_TTL_HOURS) if is_demo else None)
    db.add(r)
    db.flush()

    users = {}
    for u in seed["users"]:
        email = f"{u['role']}+{r.id}@demo.invalid" if unique_emails else u["email"]
        user = db.scalar(select(User).where(User.email == email))
        if user is None:
            # Demo sandbox accounts get an unusable password: they are reachable only via the cookie.
            pw = security.new_token() if unique_emails else u["password"]
            user = User(email=email, name=u["name"], password_hash=security.hash_password(pw)
                        if not unique_emails else "disabled$" + pw)
            db.add(user)
            db.flush()
        db.add(Membership(user_id=user.id, restaurant_id=r.id, role=u["role"]))
        users[u["role"]] = user

    device_token = security.new_token()
    cam = Camera(restaurant_id=r.id, name=seed["camera"]["name"],
                 token_hash=security.token_hash(device_token), status="online",
                 last_heartbeat_at=now)
    db.add(cam)
    db.flush()

    tables = {}
    for t in seed["tables"]:
        since = now - timedelta(minutes=rng.randint(4, 55))
        if t.get("state") == NEEDS_CLEARING:
            since = now - timedelta(minutes=3)
        table = Table(restaurant_id=r.id, label=t["label"], capacity=t["capacity"],
                      min_party=t.get("min_party", 1), x=t["x"], y=t["y"],
                      state=t.get("state", "ready"), state_since=since)
        db.add(table)
        db.flush()
        db.add(Zone(restaurant_id=r.id, camera_id=cam.id, table_id=table.id,
                    polygons=default_zone(t["x"], t["y"])))
        tables[t["label"]] = table
        if table.state == OCCUPIED:
            db.add(TableEvent(restaurant_id=r.id, table_id=table.id, source="camera",
                              type="occupancy.changed", from_state="ready", to_state=OCCUPIED,
                              observed_at=since, received_at=since, actor_name="seed"))
        if table.state == NEEDS_CLEARING:
            start = since - timedelta(minutes=50)
            db.add(TableEvent(restaurant_id=r.id, table_id=table.id, source="camera",
                              type="occupancy.changed", from_state="ready", to_state=OCCUPIED,
                              observed_at=start, received_at=start, actor_name="seed"))
            db.add(TableEvent(restaurant_id=r.id, table_id=table.id, source="camera",
                              type="occupancy.changed", from_state=OCCUPIED, to_state=NEEDS_CLEARING,
                              observed_at=since, received_at=since, actor_name="seed"))
            db.add(Alert(restaurant_id=r.id, table_id=table.id, type="needs_clearing", created_at=since))

    for p in seed.get("waitlist", []):
        db.add(WaitlistParty(restaurant_id=r.id, name=p["name"], party_size=p["party_size"],
                             arrived_at=now - timedelta(minutes=p["arrived_min_ago"])))

    if with_history:
        _synthetic_history(db, r, list(tables.values()), now, seed.get("history_days", 7), rng)
    db.commit()
    return {"restaurant": r, "users": users, "camera": cam, "device_token": device_token,
            "tables": tables}


def _synthetic_history(db, r, tables, now, days, rng):
    """Plausible past turns so analytics and the peak-hour report are not empty."""
    rows = []
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    for d in range(1, days + 1):
        day = today - timedelta(days=d)
        for table in tables:
            for start_h, end_h, p_turn in ((12, 14, 0.75), (18, 22, 0.9)):
                t = day + timedelta(hours=start_h, minutes=rng.randint(0, 40))
                while t < day + timedelta(hours=end_h):
                    if rng.random() > p_turn:
                        t += timedelta(minutes=45)
                        continue
                    leave = t + timedelta(minutes=rng.randint(35, 80))
                    ready = leave + timedelta(seconds=rng.randint(120, 540))
                    for at, src, typ, frm, to in (
                        (t, "camera", "occupancy.changed", "ready", OCCUPIED),
                        (leave, "camera", "occupancy.changed", OCCUPIED, NEEDS_CLEARING),
                        (ready, "staff", "mark_ready", NEEDS_CLEARING, "ready"),
                    ):
                        rows.append(dict(id=new_id("tev"), restaurant_id=r.id, table_id=table.id,
                                         source=src, type=typ, from_state=frm, to_state=to,
                                         applied=True, observed_at=at, received_at=at,
                                         actor_name="seed"))
                    t = ready + timedelta(minutes=rng.randint(3, 25))
    if rows:
        db.execute(TableEvent.__table__.insert(), rows)


def ensure_dev_restaurant(db: Session):
    """Local development convenience: seed 'Demo Bistro' with fixed logins once."""
    seed = load_seed()
    if db.scalar(select(User).where(User.email == seed["users"][0]["email"])):
        return None
    out = create_restaurant(db, seed)
    (config.REPO_ROOT / ".dev-device-token").write_text(out["device_token"])
    return out
