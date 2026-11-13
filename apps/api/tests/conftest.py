import os

os.environ["SEED_DEV"] = "0"
os.environ["SWEEP"] = "0"
import tempfile  # noqa: E402

# A file database (not in-memory) so tests exercise real concurrent connections.
os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/test.db")

from datetime import datetime  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import db as dbmod  # noqa: E402
from app import seed  # noqa: E402
from app.db import Base  # noqa: E402
from app.main import app  # noqa: E402

T0 = datetime(2026, 11, 2, 19, 0, 0)  # must be in the past: HTTP tests use the real clock


@pytest.fixture()
def db():
    Base.metadata.drop_all(dbmod.engine)
    Base.metadata.create_all(dbmod.engine)
    with dbmod.SessionLocal() as session:
        yield session


@pytest.fixture()
def world(db):
    """Restaurant A seeded from the demo fixture at T0, without bulk history."""
    return seed.create_restaurant(db, seed.load_seed(), now=T0, with_history=False)


@pytest.fixture()
def other(db, world):
    """Restaurant B: a second tenant with its own accounts."""
    data = seed.load_seed()
    data["name"] = "Other Place"
    for u in data["users"]:
        u["email"] = "b-" + u["email"]
    return seed.create_restaurant(db, data, now=T0, with_history=False)


@pytest.fixture()
def client(db):
    with TestClient(app) as c:
        yield c


def login(client, email, password):
    r = client.post("/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return client
