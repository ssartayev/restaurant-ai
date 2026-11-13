"""Corrections to a recording analysis: staff exclusion and manual tables (no models needed)."""
import pytest

pytest.importorskip("cv2")
pytest.importorskip("mediapipe")
pytest.importorskip("worker.detector")

from fastapi.testclient import TestClient  # noqa: E402

from app import video  # noqa: E402

TABLE = {"id": 1, "box": [0.4, 0.4, 0.6, 0.6]}
# Track 7 sits at the table for the whole clip; track 9 (a waiter) stands at it as well.
SAMPLES = [(float(t), [(0.5, 0.5, 7), (0.52, 0.48, 9)]) for t in range(10)]
DISHES = [[] for _ in SAMPLES]


def people_at_end(timeline, table=0):
    return timeline[-1][1][table]["people"], timeline[-1][1][table]["state"]


def test_marked_staff_are_left_out_of_occupancy():
    _, timeline = video.build([TABLE], SAMPLES, DISHES)
    assert people_at_end(timeline) == (2, "occupied")
    _, timeline = video.build([TABLE], SAMPLES, DISHES, staff_tracks=[9])
    assert people_at_end(timeline) == (1, "occupied")
    _, timeline = video.build([TABLE], SAMPLES, DISHES, staff_tracks=[7, 9])
    assert people_at_end(timeline) == (0, "vacant"), "a table with only staff at it is not occupied"


def test_a_table_added_by_hand_gets_its_own_occupancy():
    far = {"id": 2, "box": [0.05, 0.05, 0.2, 0.2], "manual": True}
    samples = [(float(t), [(0.5, 0.5, 7), (0.12, 0.12, 3)]) for t in range(10)]
    tables, timeline = video.build([TABLE, far], samples, DISHES)
    assert [t["id"] for t in tables] == [1, 2] and tables[1]["manual"] is True
    assert abs(tables[1]["x"] - 0.125) < 1e-9
    assert people_at_end(timeline, 0) == (1, "occupied") and people_at_end(timeline, 1) == (1, "occupied")
    _, timeline = video.build([TABLE], samples, DISHES)
    assert len(timeline[-1][1]) == 1, "removing a table removes its readings"


def test_recompute_endpoint():
    video._CACHE["abc"] = {"samples": SAMPLES, "dishes": DISHES}
    client = TestClient(video.app)
    r = client.post("/analyze/abc/recompute", json={"tables": [TABLE], "staff_tracks": [9]})
    assert r.status_code == 200 and r.json()["timeline"][-1][1][0]["people"] == 1
    assert client.post("/analyze/gone/recompute", json={"tables": []}).status_code == 404
    bad = {"tables": [{"id": 1, "box": [0.6, 0.4, 0.4, 0.6]}]}
    assert client.post("/analyze/abc/recompute", json=bad).status_code == 422
    dup = {"tables": [TABLE, TABLE]}
    assert client.post("/analyze/abc/recompute", json=dup).status_code == 422
