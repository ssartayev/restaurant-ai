import json
from pathlib import Path

import jsonschema

from worker import synth
from worker.evaluate import match, percentile, run_trace, score, summarise
from worker.occupancy_filter import FilterConfig, TableOccupancyFilter
from worker.pipeline import Pipeline
from worker.zones import Box, TableZone, anchor_point, count_people, point_in_polygon

CONTRACTS = Path(__file__).resolve().parents[3] / "packages" / "contracts" / "events"
SQUARE = [(0.2, 0.2), (0.6, 0.2), (0.6, 0.6), (0.2, 0.6)]


# ---------------------------------------------------------------- geometry

def test_point_in_polygon():
    assert point_in_polygon((0.4, 0.4), SQUARE)
    assert not point_in_polygon((0.1, 0.4), SQUARE)
    assert not point_in_polygon((0.4, 0.7), SQUARE)
    l_shape = [(0, 0), (0.6, 0), (0.6, 0.2), (0.2, 0.2), (0.2, 0.6), (0, 0.6)]
    assert point_in_polygon((0.1, 0.5), l_shape) and not point_in_polygon((0.4, 0.4), l_shape)


def test_anchor_is_lower_centre_of_box():
    x, y = anchor_point(Box(0.2, 0.2, 0.4, 0.6))
    assert abs(x - 0.3) < 1e-9 and abs(y - 0.5) < 1e-9


def test_count_people_uses_anchor_and_confidence():
    zones = [TableZone("a", [SQUARE]), TableZone("b", [[(0.7, 0.2), (0.9, 0.2), (0.9, 0.6), (0.7, 0.6)]])]
    boxes = [
        Box(0.3, 0.1, 0.4, 0.5),         # anchor (0.35, 0.4): in a
        Box(0.3, 0.1, 0.4, 0.5, 0.2),    # too uncertain: ignored
        Box(0.45, 0.0, 0.55, 0.2),       # head overlaps a, anchor (0.5, 0.15) is outside
        Box(0.75, 0.3, 0.85, 0.6),       # in b
    ]
    assert count_people(boxes, zones) == {"a": 1, "b": 1}


# ---------------------------------------------------------------- temporal filter

def feed(f, timeline, fps=2.0, t0=0.0):
    """timeline: [(duration_s, present)]. Returns [(t, new_state)] changes."""
    t, out = t0, []
    for duration, present in timeline:
        for _ in range(int(duration * fps)):
            change = f.update(t, present)
            if change is not None:
                out.append((round(t, 1), change))
            t += 1 / fps
    return out


def test_party_arrives_and_leaves():
    changes = feed(TableOccupancyFilter(), [(30, False), (600, True), (200, False)])
    assert [c for _, c in changes] == [True, False]
    arrive, leave = changes[0][0], changes[1][0]
    assert 30 + 12 <= arrive <= 30 + 22, "occupied about 14-20 s after sitting down (70% of 20 s)"
    assert 630 + 60 <= leave <= 630 + 80, "vacant about 68-75 s after leaving"


def test_walk_through_never_occupies():
    f = TableOccupancyFilter()
    assert feed(f, [(60, False), (6, True), (60, False), (8, True), (60, False)]) == []


def test_brief_stand_keeps_table_occupied():
    f = TableOccupancyFilter()
    changes = feed(f, [(10, False), (300, True), (45, False), (300, True)])
    assert [c for _, c in changes] == [True]


def test_occlusion_and_missed_detections_keep_table_occupied():
    f = TableOccupancyFilter()
    timeline = [(10, False), (60, True)] + [(3, False), (5, True)] * 40
    assert [c for _, c in feed(f, timeline)] == [True]


def test_passer_by_does_not_restart_the_vacancy_clock():
    f = TableOccupancyFilter()
    changes = feed(f, [(10, False), (300, True), (40, False), (3, True), (60, False)])
    assert [c for _, c in changes] == [True, False]
    assert changes[1][0] <= 310 + 85, "one 3 s blip costs a few seconds, not a full 75 s restart"


def test_no_decision_until_the_window_is_full():
    f = TableOccupancyFilter()
    assert feed(f, [(10, True)]) == []      # 10 s of presence is not 20 s of evidence


def test_thresholds_are_configurable():
    f = TableOccupancyFilter(FilterConfig(enter_window_s=6, exit_window_s=10))
    changes = feed(f, [(2, False), (30, True), (30, False)])
    assert [c for _, c in changes] == [True, False] and changes[1][0] < 32 + 12


# ---------------------------------------------------------------- pipeline and contract

def test_events_match_the_contract_and_carry_no_personal_data():
    schema = json.loads((CONTRACTS / "occupancy-changed.v1.schema.json").read_text())
    hb_schema = json.loads((CONTRACTS / "heartbeat.v1.schema.json").read_text())
    pipe = Pipeline([TableZone("tbl_1", [SQUARE])], camera_id="cam_1", restaurant_id="rst_1")
    events = []
    for i in range(400):
        t = 1_800_000_000 + i / 2
        events += pipe.step(t, [Box(0.35, 0.2, 0.45, 0.5, 0.9)] if i < 200 else [])
    assert [e["occupied"] for e in events] == [True, False]
    for e in events:
        jsonschema.validate(e, schema)
        assert not {"image", "frame", "track_id", "boxes"} & set(e)
    assert events[0]["sequence"] < events[1]["sequence"]
    assert len({e["event_id"] for e in events}) == 2
    hb = pipe.heartbeat(1_800_000_300)
    jsonschema.validate(hb, hb_schema)
    assert hb["zones"] == [{"table_id": "tbl_1", "occupied": False, "since": hb["zones"][0]["since"]}]


# ---------------------------------------------------------------- evaluation

def test_match_rules():
    assert match([100], [160]) == ([60], 0, 0)
    assert match([100], [95]) == ([-5], 0, 0)
    assert match([100], [80]) == ([], 1, 1)           # more than 10 s early: not this departure
    assert match([100], [300]) == ([], 1, 1)          # more than 180 s late: a miss and a false alert
    assert match([100, 200], [150]) == ([50], 1, 0)   # one prediction cannot satisfy two labels
    assert match([100], [150, 170]) == ([50], 0, 1)   # the extra one is a false alert


def test_percentile():
    assert percentile([10, 20, 30, 40, 50], 0.5) == 30 and percentile([], 0.5) is None
    assert round(percentile([10, 20, 30, 40, 50], 0.9), 1) == 46.0


def test_score_and_summary_hand_computed():
    labels = [{"table_id": "a", "type": "party_seated", "t": 100}, {"table_id": "a", "type": "party_left", "t": 1000},
              {"table_id": "b", "type": "party_seated", "t": 200}, {"table_id": "b", "type": "party_left", "t": 900}]
    preds = [{"table_id": "a", "occupied": True, "t": 118}, {"table_id": "a", "occupied": False, "t": 1070},
             {"table_id": "b", "occupied": True, "t": 215}, {"table_id": "b", "occupied": False, "t": 500},
             {"table_id": "b", "occupied": True, "t": 520}]
    s = summarise(score(labels, preds, table_hours=2.0))
    d, a = s["departure"], s["arrival"]
    assert (d["labels"], d["missed"], d["false"]) == (2, 1, 1)
    assert d["missed_rate"] == 0.5 and d["false_per_table_hour"] == 0.5 and d["delay_median_s"] == 70
    assert (a["missed"], a["false"], a["delay_median_s"]) == (0, 1, 16.5)


def test_synthetic_trace_is_reproducible_and_plain_service_is_detected():
    a, b = synth.generate(3, duration_s=2400), synth.generate(3, duration_s=2400)
    assert a["frames"] == b["frames"] and a["labels"] == b["labels"]
    s = summarise(score(a["labels"], run_trace(a), a["table_hours"]))
    assert s["departure"]["labels"] >= 6
    assert s["departure"]["missed"] == 0 and s["arrival"]["missed"] == 0
    assert s["departure"]["false"] == 0 and s["arrival"]["false"] == 0
    assert 55 <= s["departure"]["delay_median_s"] <= 90


def test_hard_tags_survive_staff_and_brief_stands():
    t = synth.generate(11, duration_s=3600, tags=("staff_pass", "brief_stand"))
    s = summarise(score(t["labels"], run_trace(t), t["table_hours"]))
    assert s["departure"]["missed"] == 0 and s["departure"]["false"] == 0 and s["arrival"]["false"] == 0
