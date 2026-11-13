"""Edge agent control flow with fakes: no camera, no network."""
import urllib.error

from worker.agent import Agent, build_pipeline, frame_health
from worker.transport import EventQueue, flush
from worker.zones import Box

CFG = {"camera_id": "cam_1", "restaurant_id": "rst_1", "config_version": 3, "thresholds": {},
       "zones": [{"table_id": "tbl_1", "label": "T1",
                  "polygons": [[[0.2, 0.2], [0.6, 0.2], [0.6, 0.6], [0.2, 0.6]]]}]}


class FakeClient:
    def __init__(self):
        self.online, self.events, self.heartbeats, self.cfg = True, [], [], dict(CFG)

    def _check(self):
        if not self.online:
            raise urllib.error.URLError("offline")

    def config(self):
        self._check()
        return self.cfg

    def send_events(self, events):
        self._check()
        self.events += events
        return {}

    def send_heartbeat(self, hb):
        self._check()
        self.heartbeats.append(hb)
        return {}


class FakeDetector:
    def __init__(self):
        self.present = False

    def detect(self, frame):
        return [Box(0.35, 0.2, 0.45, 0.5, 0.9)] if self.present else []


def make(tmp_path):
    client, det = FakeClient(), FakeDetector()
    clock = {"t": 1_800_000_000.0}
    agent = Agent(client, EventQueue(str(tmp_path / "q.db")), det, clock=lambda: clock["t"])
    return agent, client, det, clock


def run(agent, clock, seconds):
    for _ in range(int(seconds * 2)):
        clock["t"] += 0.5
        agent.process(frame=None)


def test_events_and_heartbeats_flow(tmp_path):
    agent, client, det, clock = make(tmp_path)
    det.present = True
    run(agent, clock, 40)
    assert [e["occupied"] for e in client.events] == [True]
    assert client.events[0]["camera_id"] == "cam_1" and client.events[0]["config_version"] == 3
    assert 2 <= len(client.heartbeats) <= 4, "one heartbeat per 15 s"
    assert client.heartbeats[-1]["zones"][0]["occupied"] is True


def test_store_and_forward_survives_an_outage(tmp_path):
    agent, client, det, clock = make(tmp_path)
    run(agent, clock, 5)
    client.online = False
    det.present = True
    run(agent, clock, 40)                      # the arrival happens while offline
    assert client.events == [] and len(agent.queue) == 1
    reopened = EventQueue(str(tmp_path / "q.db"))
    assert len(reopened) == 1, "the queue is on disk: it survives a restart"
    client.online = True
    run(agent, clock, 2)
    assert [e["occupied"] for e in client.events] == [True] and len(agent.queue) == 0


def test_permanently_rejected_batch_is_dropped_not_retried_forever(tmp_path):
    q = EventQueue(str(tmp_path / "q.db"))
    q.put({"bad": True})

    class Rejecting:
        def send_events(self, events):
            raise urllib.error.HTTPError("u", 422, "bad", None, None)

    assert flush(q, Rejecting()) == 0 and len(q) == 0


def test_config_change_rebuilds_zones_but_keeps_state(tmp_path):
    agent, client, det, clock = make(tmp_path)
    det.present = True
    run(agent, clock, 40)
    client.cfg = {**CFG, "config_version": 4, "thresholds": {"exit_window_s": 30},
                  "zones": CFG["zones"] + [{"table_id": "tbl_2", "label": "T2",
                                            "polygons": [[[0.7, 0.2], [0.9, 0.2], [0.9, 0.6]]]}]}
    run(agent, clock, 70)                      # past the 60 s config poll
    assert agent.pipeline.config_version == 4 and set(agent.pipeline.filters) == {"tbl_1", "tbl_2"}
    assert agent.pipeline.filters["tbl_1"].occupied is True
    assert agent.pipeline.cfg.exit_window_s == 30


def test_build_pipeline_and_frame_health():
    import numpy as np
    assert build_pipeline(CFG).zones[0].polygons[0][0] == (0.2, 0.2)
    assert frame_health(np.zeros((10, 10, 3), dtype=np.uint8))[0] == "degraded"
    assert frame_health(np.full((10, 10, 3), 128, dtype=np.uint8))[1].startswith("image has no detail")
    rng = np.random.default_rng(0)
    assert frame_health(rng.integers(40, 200, (10, 10, 3)).astype(np.uint8)) == ("ok", None)
