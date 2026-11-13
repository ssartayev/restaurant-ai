"""Edge agent: runs on the box in the restaurant.

  camera (RTSP, LAN only) -> sample ~2 fps -> person detector -> Pipeline -> queue -> HTTPS

Frames stay in memory and are never written to disk or uploaded. Only table-level
JSON leaves the building. No inbound ports are needed.

STATUS: the control flow, queue and transport are covered by tests with a fake frame
source. The RTSP capture and the ONNX detector have NOT been run against a real camera
in this repository (AGENTS.md section 8, tasks CV-1 and EDGE-1).

Run:  python -m worker.agent --api https://example.org --token-file device.token \
          --source rtsp://camera.local/stream1 --model yolox_s.onnx
"""
import argparse
import time

from .detector import Detector
from .occupancy_filter import FilterConfig
from .pipeline import Pipeline
from .transport import ApiClient, EventQueue, flush
from .zones import TableZone, point_in_polygon
from .tableware import TABLEWARE_CLASSES, counts_by_surface

HEARTBEAT_S, CONFIG_POLL_S = 15.0, 60.0


def build_pipeline(cfg: dict, previous: Pipeline | None = None) -> Pipeline:
    zones = [TableZone(z["table_id"], [[tuple(p) for p in poly] for poly in z["polygons"]],
                       z.get("label", "")) for z in cfg["zones"]]
    pipe = Pipeline(zones, FilterConfig.from_dict(cfg.get("thresholds")),
                    camera_id=cfg.get("camera_id"), restaurant_id=cfg.get("restaurant_id"),
                    config_version=cfg.get("config_version", 0))
    if previous:  # keep what we already know about tables whose zone still exists
        pipe.sequence = previous.sequence
        for tid, f in previous.filters.items():
            if tid in pipe.filters:
                pipe.filters[tid] = f
                f.cfg = pipe.cfg
    return pipe


def frame_health(frame) -> tuple[str, str | None]:
    """Cheap image checks: a covered, dark or washed-out lens is reported as degraded."""
    mean = float(frame.mean())
    if mean < 25:
        return "degraded", "image too dark"
    if mean > 240:
        return "degraded", "image overexposed"
    if float(frame.std()) < 6:
        return "degraded", "image has no detail (lens covered?)"
    return "ok", None


class Agent:
    def __init__(self, client: ApiClient, queue: EventQueue, detector: Detector, *,
                 clock=time.time):
        self.client, self.queue, self.detector, self.clock = client, queue, detector, clock
        self.pipeline: Pipeline | None = None
        self._last_hb = self._last_cfg = 0.0
        self.tableware: dict[str, int] = {}
        self.health: tuple[str, str | None] = ("ok", None)

    def refresh_config(self, force: bool = False) -> bool:
        now = self.clock()
        if not force and now - self._last_cfg < CONFIG_POLL_S:
            return False
        self._last_cfg = now
        try:
            cfg = self.client.config()
        except Exception:
            return False  # keep running on the last known configuration
        if self.pipeline is None or cfg.get("config_version") != self.pipeline.config_version:
            self.pipeline = build_pipeline(cfg, self.pipeline)
            return True
        return False

    def process(self, frame, t: float | None = None) -> list[dict]:
        """Handle one sampled frame. Safe to call when offline: events wait in the queue."""
        t = self.clock() if t is None else t
        self.refresh_config()
        if self.pipeline is None:
            return []
        if hasattr(frame, "mean"):
            self.health = frame_health(frame)
        detect_classes = getattr(self.detector, "detect_classes", None)
        if detect_classes and self.health[0] == "ok":
            detections = detect_classes(frame, (0, 60, *TABLEWARE_CLASSES))
            surfaces = detections[60]
            items = [box for category in TABLEWARE_CLASSES for box in detections[category]]
            self.tableware = {}
            for surface, count in zip(surfaces, counts_by_surface(surfaces, items)):
                center = ((surface.x1 + surface.x2) / 2, (surface.y1 + surface.y2) / 2)
                zone = next((z for z in self.pipeline.zones if any(
                    point_in_polygon(center, poly) for poly in z.polygons)), None)
                if zone:
                    self.tableware[zone.table_id] = max(count, self.tableware.get(zone.table_id, 0))
            people = detections[0]
        else:
            self.tableware = {}
            people = self.detector.detect(frame)
        events = self.pipeline.step(t, people) if self.health[0] == "ok" else []
        for ev in events:
            self.queue.put(ev)
        flush(self.queue, self.client)
        if t - self._last_hb >= HEARTBEAT_S:
            self._last_hb = t
            try:
                heartbeat = self.pipeline.heartbeat(t, *self.health)
                if self.health[0] != "ok":
                    heartbeat["zones"] = []
                for zone in heartbeat["zones"]:
                    table_id = zone["table_id"]
                    if table_id in self.tableware:
                        zone["tableware_count"] = min(self.tableware[table_id], 100)
                    zone["people_present"] = self.pipeline._last_counts.get(table_id, 0) > 0
                self.client.send_heartbeat(heartbeat)
            except Exception:
                pass  # the server marks the camera offline after 45 s without heartbeats
        return events


def capture_loop(agent: Agent, source: str, fps: float = 2.0):
    """Read the newest frame at `fps`, reconnecting with backoff when the stream drops."""
    import cv2
    backoff = 1.0
    while True:
        cap = cv2.VideoCapture(source)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not cap.isOpened():
            time.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
            continue
        backoff, next_at, failures = 1.0, time.time(), 0
        while failures < 10:
            ok = cap.grab()  # grab every frame so we always decode the NEWEST one
            if not ok:
                failures += 1
                time.sleep(0.2)
                continue
            failures = 0
            if time.time() < next_at:
                continue
            next_at = time.time() + 1.0 / fps
            ok, frame = cap.retrieve()
            if ok:
                agent.process(frame)
        cap.release()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", required=True)
    ap.add_argument("--token-file", required=True)
    ap.add_argument("--source", required=True, help="RTSP URL or video file")
    ap.add_argument("--model", required=True, help="YOLOX ONNX file")
    ap.add_argument("--queue", default="queue.db")
    ap.add_argument("--fps", type=float, default=2.0)
    args = ap.parse_args()
    from .detector import OnnxYoloxDetector
    token = open(args.token_file).read().strip()
    agent = Agent(ApiClient(args.api, token), EventQueue(args.queue), OnnxYoloxDetector(args.model))
    agent.refresh_config(force=True)
    capture_loop(agent, args.source, args.fps)


if __name__ == "__main__":
    main()
