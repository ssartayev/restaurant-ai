"""R6: a restaurant cannot access another restaurant's data.

The suite walks EVERY route in the OpenAPI document. A new /restaurants/{rid} route is
covered automatically; a new route that is not tenant-scoped must be added to PUBLIC or
DEVICE below, otherwise the test fails.
"""
from sqlalchemy import select

from app.main import app
from app.models import Alert, Camera, WaitlistParty

from .conftest import login

PUBLIC = {"/healthz", "/v1/auth/login", "/v1/auth/logout", "/v1/demo/sessions"}
SESSION_ONLY = {"/v1/me"}
DEVICE = {"/v1/ingest/events", "/v1/ingest/heartbeat", "/v1/worker/config"}


def routes():
    for path, methods in app.openapi()["paths"].items():
        for method in methods:
            yield method.upper(), path


def test_every_route_is_classified():
    for _, path in routes():
        assert path.startswith("/v1/restaurants/{rid}") or path in PUBLIC | SESSION_ONLY | DEVICE, \
            f"unclassified route {path}: decide how it is tenant-scoped and add a test"


def fill(path, ids):
    for key, value in ids.items():
        path = path.replace("{" + key + "}", value)
    assert "{" not in path, path
    return path


def test_cross_tenant_access_is_404_for_every_route_and_role(client, world, other, db):
    a = world["restaurant"].id
    ids = {
        "rid": a,
        "tid": world["tables"]["T5"].id,
        "aid": db.scalar(select(Alert.id).where(Alert.restaurant_id == a)),
        "pid": db.scalar(select(WaitlistParty.id).where(WaitlistParty.restaurant_id == a)),
        "cid": db.scalar(select(Camera.id).where(Camera.restaurant_id == a)),
        "uid": world["users"]["staff"].id,
    }
    checked = 0
    for role in ("admin", "host", "staff"):
        login(client, f"b-{role}@demo.test", f"demo-{role}")
        for method, path in routes():
            if not path.startswith("/v1/restaurants/{rid}"):
                continue
            r = client.request(method, fill(path, ids), json={})
            assert r.status_code == 404, f"{role} of B got {r.status_code} on {method} {path}"
            checked += 1
    assert checked >= 60


def test_unauthenticated_requests_are_401(client, world):
    ids = {"rid": world["restaurant"].id, "tid": "x", "aid": "x", "pid": "x", "cid": "x", "uid": "x"}
    for method, path in routes():
        if path.startswith("/v1/restaurants/{rid}") or path in SESSION_ONLY | DEVICE:
            r = client.request(method, fill(path, ids), json={})
            assert r.status_code == 401, f"{method} {path} -> {r.status_code}"


def test_same_restaurant_but_foreign_child_ids_are_404(client, world, other):
    """B's admin uses B's restaurant ID with A's table: scoping must check the child too."""
    login(client, "b-admin@demo.test", "demo-admin")
    b, a_table = other["restaurant"].id, world["tables"]["T5"].id
    r = client.post(f"/v1/restaurants/{b}/tables/{a_table}/commands", json={"command": "mark_ready"})
    assert r.status_code == 404
    assert client.get(f"/v1/restaurants/{b}/tables/{a_table}/events").status_code == 404
    assert client.delete(f"/v1/restaurants/{b}/tables/{a_table}").status_code == 404


def test_role_matrix(client, world):
    rid = world["restaurant"].id
    admin_only = [("GET", f"/v1/restaurants/{rid}/members"), ("GET", f"/v1/restaurants/{rid}/cameras"),
                  ("GET", f"/v1/restaurants/{rid}/analytics/summary"), ("GET", f"/v1/restaurants/{rid}/export"),
                  ("PATCH", f"/v1/restaurants/{rid}/settings")]
    for role, expected in (("staff", 403), ("host", 403), ("admin", 200)):
        login(client, f"{role}@demo.test", f"demo-{role}")
        for method, path in admin_only:
            assert client.request(method, path, json={}).status_code == expected, (role, path)


def test_deactivated_user_loses_access_immediately(client, world):
    rid = world["restaurant"].id
    from fastapi.testclient import TestClient
    with TestClient(app) as staff:
        login(staff, "staff@demo.test", "demo-staff")
        assert staff.get(f"/v1/restaurants/{rid}/floor").status_code == 200
        login(client, "admin@demo.test", "demo-admin")
        uid = world["users"]["staff"].id
        assert client.patch(f"/v1/restaurants/{rid}/members/{uid}", json={"active": False}).status_code == 200
        assert staff.get(f"/v1/restaurants/{rid}/floor").status_code == 401


def test_demo_sandboxes_are_isolated_and_reset_independently(db):
    from fastapi.testclient import TestClient
    with TestClient(app) as one, TestClient(app) as two:
        a = one.post("/v1/demo/sessions").json()["restaurant_id"]
        b = two.post("/v1/demo/sessions").json()["restaurant_id"]
        assert a != b
        assert one.get(f"/v1/restaurants/{b}/floor").status_code == 404
        fa = one.get(f"/v1/restaurants/{a}/floor").json()
        t5 = next(t for t in fa["tables"] if t["label"] == "T5")
        one.post(f"/v1/restaurants/{a}/tables/{t5['id']}/commands", json={"command": "mark_ready"})
        two.post(f"/v1/restaurants/{b}/waitlist", json={"name": "Viewer Two", "party_size": 2})
        # Viewer one resets. Viewer two keeps their changes.
        assert one.post(f"/v1/restaurants/{a}/demo/scenario", json={"action": "reset"}).json() == {"reset": True}
        fa = one.get(f"/v1/restaurants/{a}/floor").json()
        assert next(t for t in fa["tables"] if t["label"] == "T5")["state"] == "needs_clearing"
        assert len(fa["tables"]) == 12 and len(fa["waitlist"]) == 5
        fb = two.get(f"/v1/restaurants/{b}/floor").json()
        assert "Viewer Two" in [p["name"] for p in fb["waitlist"]]
        # Role switch inside a sandbox.
        assert one.post(f"/v1/restaurants/{a}/demo/role", json={"role": "staff"}).status_code == 200
        assert one.get(f"/v1/restaurants/{a}/floor").json()["role"] == "staff"
        assert one.get(f"/v1/restaurants/{a}/analytics/summary").status_code == 403


def test_expired_sandbox_is_deleted(db):
    from datetime import timedelta

    from fastapi.testclient import TestClient

    from app import config, service
    from app.models import Restaurant, Table, User
    from app.util import utcnow
    with TestClient(app) as c:
        rid = c.post("/v1/demo/sessions").json()["restaurant_id"]
    out = service.sweep(db, utcnow() + timedelta(hours=config.DEMO_TTL_HOURS + 1))
    assert out["expired"] == 1
    assert db.get(Restaurant, rid) is None
    assert db.scalars(select(Table).where(Table.restaurant_id == rid)).all() == []
    assert db.scalars(select(User)).all() == []
