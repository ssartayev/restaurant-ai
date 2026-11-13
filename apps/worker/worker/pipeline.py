"""Detections -> table-level events. No I/O: easy to test and to run anywhere.

frame boxes --count_people--> people per table --TableOccupancyFilter--> occupancy.changed events
"""
import secrets
from datetime import datetime, timezone

from . import __version__
from .occupancy_filter import FilterConfig, TableOccupancyFilter
from .zones import Box, TableZone, count_people


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Pipeline:
    def __init__(self, zones: list[TableZone], cfg: FilterConfig | None = None, *,
                 camera_id: str | None = None, restaurant_id: str | None = None,
                 config_version: int = 0, min_conf: float = 0.35, anchor: tuple[float, float] = (0.5, 0.75)):
        self.zones, self.cfg = zones, cfg or FilterConfig()
        self.camera_id, self.restaurant_id = camera_id, restaurant_id
        self.config_version, self.min_conf, self.anchor = config_version, min_conf, anchor
        self.filters = {z.table_id: TableOccupancyFilter(self.cfg) for z in zones}
        self.sequence = 0
        self._last_counts: dict[str, int] = {}

    def step(self, t: float, boxes: list[Box]) -> list[dict]:
        """Process one sampled frame taken at epoch time t. Returns zero or more events."""
        counts = count_people(boxes, self.zones, min_conf=self.min_conf,
                              ax=self.anchor[0], ay=self.anchor[1])
        self._last_counts = counts
        confs = [b.conf for b in boxes if b.conf >= self.min_conf]
        events = []
        for table_id, n in counts.items():
            change = self.filters[table_id].update(t, n > 0)
            if change is None:
                continue
            self.sequence += 1
            event = {
                "schema_version": 1,
                "event_id": "evt_" + secrets.token_hex(12),
                "type": "occupancy.changed",
                "table_id": table_id,
                "occupied": change,
                "person_count": n,
                "confidence": round(sum(confs) / len(confs), 3) if confs else 1.0,
                "observed_at": iso(t),
                "window_s": self.cfg.enter_window_s if change else self.cfg.exit_window_s,
                "sequence": self.sequence,
                "worker_version": __version__,
                "config_version": self.config_version,
            }
            if self.camera_id:
                event["camera_id"] = self.camera_id
            if self.restaurant_id:
                event["restaurant_id"] = self.restaurant_id
            events.append(event)
        return events

    def heartbeat(self, t: float, health: str = "ok", reason: str | None = None) -> dict:
        """Snapshot of every zone. Lets the server repair a lost event and release holds."""
        self.sequence += 1
        hb = {
            "schema_version": 1, "type": "camera.heartbeat", "sequence": self.sequence,
            "sent_at": iso(t), "health": health, "worker_version": __version__,
            "zones": [{"table_id": tid, "occupied": f.occupied,
                       **({"since": iso(f.since)} if f.since else {})}
                      for tid, f in self.filters.items()],
        }
        if reason:
            hb["health_reason"] = reason[:200]
        if self.camera_id:
            hb["camera_id"] = self.camera_id
        return hb
