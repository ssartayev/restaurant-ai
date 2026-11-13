"""R12: analytics numbers match values computed by hand."""
from datetime import datetime, timedelta

from app import analytics, seed
from app.models import Organization, Restaurant, Table, TableEvent


def test_summary_and_peak_hours_hand_computed(db):
    org = Organization(name="o")
    db.add(org)
    db.flush()
    r = Restaurant(organization_id=org.id, name="r", timezone="Asia/Almaty")
    db.add(r)
    db.flush()
    t1 = Table(restaurant_id=r.id, label="A", capacity=2)
    t2 = Table(restaurant_id=r.id, label="B", capacity=4)
    db.add_all([t1, t2])
    db.flush()
    day = datetime(2026, 11, 9, 0, 0)  # a Monday, UTC

    def e(table, minute, to):
        at = day + timedelta(hours=12, minutes=minute)
        db.add(TableEvent(restaurant_id=r.id, table_id=table.id, source="camera", type="x",
                          to_state=to, applied=True, observed_at=at, received_at=at))

    # Table A: occupied 12:00-13:00 (60 min), cleared in 4 min; occupied 13:10-13:40 (30), cleared in 6.
    e(t1, 0, "occupied"); e(t1, 60, "needs_clearing"); e(t1, 64, "ready")
    e(t1, 70, "occupied"); e(t1, 100, "needs_clearing"); e(t1, 106, "ready")
    # Table B: occupied 12:30-13:00 (30 min), cleared in 8 min.
    e(t2, 30, "occupied"); e(t2, 60, "needs_clearing"); e(t2, 68, "ready")
    # An ignored camera event must not count.
    db.add(TableEvent(restaurant_id=r.id, table_id=t2.id, source="camera", type="x", to_state=None,
                      applied=False, reason="ignored_state", observed_at=day + timedelta(hours=13),
                      received_at=day))
    db.commit()

    start, end = day + timedelta(hours=12), day + timedelta(hours=14)
    s = analytics.summary(db, r.id, start, end, now=end + timedelta(days=1))
    assert s["turns"] == 3 and s["turns_per_table"] == 1.5
    assert s["avg_turn_minutes"] == 40.0               # (60 + 30 + 30) / 3
    assert s["median_departure_to_ready_minutes"] == 6.0  # median of 4, 6, 8
    assert s["occupancy_pct"] == 50.0                  # 120 occupied minutes / (2 tables x 120 minutes)

    p = analytics.peak_hours(db, r.id, r.timezone, day, day + timedelta(days=7))
    # 12:00, 12:30 and 13:10 UTC are 17:00, 17:30 and 18:10 in Almaty (UTC+5).
    assert {(x["weekday"], x["hour"]): x["arrivals"] for x in p["by_hour"]} == {(0, 17): 2, (0, 18): 1}
    assert p["by_shift"] == [{"weekday": 0, "shift": "dinner", "arrivals": 3, "per_week": 3.0}]


def test_seeded_demo_has_non_empty_analytics(db):
    now = datetime(2026, 11, 13, 19, 0)
    out = seed.create_restaurant(db, seed.load_seed(), now=now)
    s = analytics.summary(db, out["restaurant"].id, now - timedelta(days=7), now, now)
    assert s["turns"] > 100 and s["median_departure_to_ready_minutes"] > 0
