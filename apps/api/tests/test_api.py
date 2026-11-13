"""HTTP-level tests: ingest idempotency and ordering, commands and conflicts, alerts, waitlist."""
import json
import threading
from datetime import datetime, timedelta, timezone

import jsonschema
import pytest
from sqlalchemy import select

from app import config, service
from app.models import Alert, TableEvent, WaitlistParty
from app.util import utcnow

from .conftest import T0, login


def ev(table_id, occupied, event_id, at=None):
    at = at or datetime.now(timezone.utc)
    return {"schema_version": 1, "event_id": event_id, "type": "occupancy.changed",
            "table_id": table_id, "occupied": occupied, "observed_at": at.isoformat()}


def ingest(client, token, *events):
    r = client.post("/v1/ingest/events", json={"events": list(events)},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    return [x["result"] for x in r.json()["results"]]


def beat(client, token, zones=()):
    r = client.post("/v1/ingest/heartbeat", headers={"Authorization": f"Bearer {token}"}, json={
        "schema_version": 1, "type": "camera.heartbeat",
        "sent_at": datetime.now(timezone.utc).isoformat(), "zones": list(zones)})
    assert r.status_code == 200, r.text
    return r.json()


def floor(client, rid):
    r = client.get(f"/v1/restaurants/{rid}/floor")
    assert r.status_code == 200, r.text
    return r.json()


def tbl(fl, label):
    return next(t for t in fl["tables"] if t["label"] == label)


def test_healthz(client):
    assert client.get("/healthz").json()["status"] == "ok"


def test_contract_examples_validate():
    schema = json.loads((config.CONTRACTS_DIR / "events/occupancy-changed.v1.schema.json").read_text())
    good = ev("tbl_x", True, "evt_12345678")
    jsonschema.validate(good, schema)
    for bad in ({**good, "face_embedding": [0.1]}, {**good, "schema_version": 2},
                {k: v for k, v in good.items() if k != "observed_at"}):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(bad, schema)


def test_ingest_requires_device_token_and_rejects_extra_fields(client, world):
    t2 = world["tables"]["T2"].id
    assert client.post("/v1/ingest/events", json={"events": []}).status_code == 401
    assert client.post("/v1/ingest/events", json={"events": []},
                       headers={"Authorization": "Bearer nope"}).status_code == 401
    bad = {**ev(t2, True, "evt_extra_001"), "image": "base64..."}
    r = client.post("/v1/ingest/events", json={"events": [bad]},
                    headers={"Authorization": f"Bearer {world['device_token']}"})
    assert r.status_code == 422  # R11: nothing image-like can enter the system


def test_ingest_applied_duplicate_stale(client, world, db):
    tok, t2 = world["device_token"], world["tables"]["T2"].id
    now = datetime.now(timezone.utc)
    assert ingest(client, tok, ev(t2, True, "evt_a_000001", now)) == ["applied"]
    assert ingest(client, tok, ev(t2, True, "evt_a_000001", now)) == ["duplicate"]
    assert ingest(client, tok, ev(t2, False, "evt_a_000002", now - timedelta(seconds=20))) == ["ignored_stale"]
    assert ingest(client, tok, ev(t2, False, "evt_a_000003", now - timedelta(minutes=10))) == ["ignored_stale"]
    assert ingest(client, tok, ev(t2, False, "evt_a_000004", now + timedelta(milliseconds=5))) == ["applied"]
    rows = db.scalars(select(TableEvent).where(TableEvent.table_id == t2,
                                               TableEvent.camera_event_id.is_not(None))).all()
    assert len(rows) == 4, "ignored events are kept for history; the duplicate is not stored twice"
    assert len(db.scalars(select(Alert).where(Alert.table_id == t2)).all()) == 1


def test_ingest_rejects_table_of_another_restaurant(client, world, other):
    foreign = other["tables"]["T2"].id
    assert ingest(client, world["device_token"], ev(foreign, True, "evt_x_000001")) == ["rejected"]
    login(client, "b-admin@demo.test", "demo-admin")
    assert tbl(floor(client, other["restaurant"].id), "T2")["state"] == "ready"


def test_command_conflict_and_idempotency(client, world):
    rid, t5 = world["restaurant"].id, world["tables"]["T5"]
    login(client, "staff@demo.test", "demo-staff")
    url = f"/v1/restaurants/{rid}/tables/{t5.id}/commands"
    v = tbl(floor(client, rid), "T5")["version"]
    r = client.post(url, json={"command": "mark_ready", "expected_version": v})
    assert r.json()["result"] == "applied" and r.json()["table"]["manual_hold"] is True
    # Same target with the old version: idempotent no-op.
    assert client.post(url, json={"command": "mark_ready", "expected_version": v}).json()["result"] == "no_change"
    # Different target with the old version: conflict, with the fresh table in the body.
    r = client.post(url, json={"command": "mark_occupied", "expected_version": v})
    assert r.status_code == 409 and r.json()["detail"]["table"]["state"] == "ready"
    assert "Timur" in r.json()["detail"]["changed_by"]
    assert client.post(url, json={"command": "explode"}).status_code == 422


def test_parallel_identical_commands_produce_one_event(client, world, db):
    """R5: twenty staff tap Mark Ready at once."""
    rid, t5 = world["restaurant"].id, world["tables"]["T5"]
    login(client, "staff@demo.test", "demo-staff")
    v = tbl(floor(client, rid), "T5")["version"]
    codes = []

    def tap():
        r = client.post(f"/v1/restaurants/{rid}/tables/{t5.id}/commands",
                        json={"command": "mark_ready", "expected_version": v})
        codes.append((r.status_code, r.json().get("result")))

    threads = [threading.Thread(target=tap) for _ in range(20)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert all(code == 200 for code, _ in codes), codes
    assert [res for _, res in codes].count("applied") == 1
    events = db.scalars(select(TableEvent).where(TableEvent.table_id == t5.id,
                                                 TableEvent.type == "mark_ready")).all()
    assert len(events) == 1


def test_alert_dedupe_ack_resolve(client, world, db):
    rid, tok, t1 = world["restaurant"].id, world["device_token"], world["tables"]["T1"].id
    login(client, "staff@demo.test", "demo-staff")
    now = datetime.now(timezone.utc)
    assert ingest(client, tok, ev(t1, False, "evt_leave_01", now)) == ["applied"]
    assert ingest(client, tok, ev(t1, False, "evt_leave_02", now + timedelta(milliseconds=3))) == ["ignored_state"]
    alerts = [a for a in floor(client, rid)["alerts"] if a["table_id"] == t1]
    assert len(alerts) == 1 and alerts[0]["status"] == "open"
    r = client.post(f"/v1/restaurants/{rid}/alerts/{alerts[0]['id']}/ack")
    assert r.json()["alert"]["acknowledged_by"].startswith("Timur")
    assert client.post(f"/v1/restaurants/{rid}/alerts/{alerts[0]['id']}/ack").json()["result"] == "no_change"
    client.post(f"/v1/restaurants/{rid}/tables/{t1}/commands", json={"command": "mark_ready"})
    assert [a for a in floor(client, rid)["alerts"] if a["table_id"] == t1] == []


def test_renotify_once_never_a_second_alert(db, world):
    t5 = world["tables"]["T5"]
    later = T0 + timedelta(seconds=config.RENOTIFY_S + 1)
    assert service.sweep(db, later)["renotify"] == 1
    assert service.sweep(db, later + timedelta(minutes=10))["renotify"] == 0
    assert len(db.scalars(select(Alert).where(Alert.table_id == t5.id)).all()) == 1


def test_waitlist_roles_suggestion_and_seat(client, world):
    rid = world["restaurant"].id
    login(client, "staff@demo.test", "demo-staff")
    assert client.post(f"/v1/restaurants/{rid}/waitlist",
                       json={"name": "Zed", "party_size": 2}).status_code == 403
    login(client, "host@demo.test", "demo-host")
    fl = floor(client, rid)
    names = {p["id"]: p["name"] for p in fl["waitlist"]}
    t2 = tbl(fl, "T2")
    sug = {s["table_id"]: names[s["party_id"]] for s in fl["suggestions"]}
    assert sug == {t2["id"]: "Lee"}, "Kim (4) arrived first but does not fit a two-top"
    lee = next(p for p in fl["waitlist"] if p["name"] == "Lee")
    r = client.post(f"/v1/restaurants/{rid}/tables/{t2['id']}/seat",
                    json={"party_id": lee["id"], "expected_version": t2["version"]})
    assert r.status_code == 200 and r.json()["party"]["status"] == "seated"
    assert r.json()["table"]["state"] == "occupied" and r.json()["table"]["current_party_id"] == lee["id"]
    # The table is no longer ready: a second seating attempt seats nobody.
    nowak = next(p for p in fl["waitlist"] if p["name"] == "Nowak")
    r = client.post(f"/v1/restaurants/{rid}/tables/{t2['id']}/seat", json={"party_id": nowak["id"]})
    assert r.status_code == 409
    assert "Nowak" in [p["name"] for p in floor(client, rid)["waitlist"]]


def test_suggestion_rule_unit(db, world):
    from app.models import Table
    tables = db.scalars(select(Table)).all()
    for t in tables:
        t.state = "ready"
    parties = db.scalars(select(WaitlistParty)).all()
    by_label = {t.id: t.label for t in tables}
    by_name = {p.id: p.name for p in parties}
    got = {by_label[t]: by_name[p] for t, p in service.suggest_seating(tables, parties).items()}
    # Two-tops first, longest wait first among those that fit; T11 needs a party of 5+.
    assert got["T1"] == "Lee" and got["T2"] == "Nowak"
    assert got["T4"] == "Kim" and got["T5"] == "Garcia" and got["T9"] == "Okafor"
    assert "T11" not in got


def test_camera_offline_after_timeout_then_hold_on_return(client, world, db):
    rid, tok = world["restaurant"].id, world["device_token"]
    t7 = world["tables"]["T7"].id
    login(client, "staff@demo.test", "demo-staff")
    beat(client, tok)
    assert service.sweep(db, utcnow() + timedelta(seconds=config.HEARTBEAT_TIMEOUT_S + 1))["offline"] == 1
    assert floor(client, rid)["cameras"][0]["status"] == "offline"
    assert ingest(client, tok, ev(t7, False, "evt_off_0001")) == ["ignored_camera_offline"]
    # Manual operation keeps working.
    client.post(f"/v1/restaurants/{rid}/tables/{t7}/commands", json={"command": "mark_needs_clearing"})
    client.post(f"/v1/restaurants/{rid}/tables/{t7}/commands", json={"command": "mark_ready"})
    # Camera returns and wrongly claims T1 is empty: held, so nothing flips.
    t1 = world["tables"]["T1"].id
    beat(client, tok, [{"table_id": t1, "occupied": False}, {"table_id": t7, "occupied": False}])
    fl = floor(client, rid)
    assert fl["cameras"][0]["status"] == "online"
    assert tbl(fl, "T1")["state"] == "occupied" and tbl(fl, "T1")["manual_hold"] is True
    assert tbl(fl, "T7")["state"] == "ready" and tbl(fl, "T7")["manual_hold"] is False


def test_automation_kill_switch(client, world):
    rid, tok, t2 = world["restaurant"].id, world["device_token"], world["tables"]["T2"].id
    login(client, "admin@demo.test", "demo-admin")
    assert client.patch(f"/v1/restaurants/{rid}/settings", json={"automation_enabled": False}).status_code == 200
    assert ingest(client, tok, ev(t2, True, "evt_kill_001")) == ["ignored_automation_off"]
    assert tbl(floor(client, rid), "T2")["state"] == "ready"


def test_greeted_reminder(client, world, db):
    rid, t1 = world["restaurant"].id, world["tables"]["T1"].id
    login(client, "admin@demo.test", "demo-admin")
    assert service.sweep(db, T0 + timedelta(hours=1))["greet"] == 0, "off by default"
    client.patch(f"/v1/restaurants/{rid}/settings", json={"greet_reminders": True})
    db.expire_all()
    assert service.sweep(db, T0 + timedelta(hours=1))["greet"] >= 1
    assert service.sweep(db, T0 + timedelta(hours=2))["greet"] == 0, "no duplicate reminders"
    r = client.post(f"/v1/restaurants/{rid}/tables/{t1}/commands", json={"command": "mark_greeted"})
    assert r.json()["result"] == "applied" and r.json()["table"]["greeted_at"]
    assert not [a for a in floor(client, rid)["alerts"]
                if a["table_id"] == t1 and a["type"] == "greet_reminder"]


def test_setup_zone_config_reaches_worker(client, world):
    rid, tok = world["restaurant"].id, world["device_token"]
    login(client, "admin@demo.test", "demo-admin")
    r = client.post(f"/v1/restaurants/{rid}/tables", json={"label": "T20", "capacity": 4, "x": 0.9, "y": 0.9})
    assert r.status_code == 201
    tid = r.json()["id"]
    cam = client.get(f"/v1/restaurants/{rid}/cameras").json()[0]
    poly = [[[0.8, 0.8], [0.95, 0.8], [0.95, 0.95], [0.8, 0.95]]]
    r = client.put(f"/v1/restaurants/{rid}/tables/{tid}/zone", json={"camera_id": cam["id"], "polygons": poly})
    assert r.status_code == 200 and r.json()["config_version"] == cam["config_version"] + 1
    cfg = client.get("/v1/worker/config", headers={"Authorization": f"Bearer {tok}"}).json()
    assert next(z for z in cfg["zones"] if z["label"] == "T20")["polygons"] == poly
    bad = [[[0.8, 0.8], [1.5, 0.8], [0.9, 0.9]]]
    assert client.put(f"/v1/restaurants/{rid}/tables/{tid}/zone",
                      json={"camera_id": cam["id"], "polygons": bad}).status_code == 422


def test_history_endpoint(client, world):
    rid, t5 = world["restaurant"].id, world["tables"]["T5"].id
    login(client, "staff@demo.test", "demo-staff")
    client.post(f"/v1/restaurants/{rid}/tables/{t5}/commands", json={"command": "mark_ready"})
    rows = client.get(f"/v1/restaurants/{rid}/tables/{t5}/events").json()
    assert rows[0]["type"] == "mark_ready" and rows[0]["actor"].startswith("Timur")
    assert rows[0]["from_state"] == "needs_clearing" and rows[0]["to_state"] == "ready"


def test_retention_scrubs_waitlist_pii(db, world):
    p = db.scalars(select(WaitlistParty)).first()
    p.status, p.phone, p.closed_at = "cancelled", "+100000000", T0
    db.commit()
    assert service.sweep(db, T0 + timedelta(hours=config.WAITLIST_PII_HOURS - 1))["scrubbed"] == 0
    assert service.sweep(db, T0 + timedelta(hours=config.WAITLIST_PII_HOURS + 1))["scrubbed"] == 1
    db.refresh(p)
    assert p.name is None and p.phone is None and p.party_size > 0
