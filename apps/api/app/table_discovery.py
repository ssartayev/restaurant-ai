"""Find the tables of a fixed-camera recording from many weak detections.

A table does not move, so evidence can be added up over the whole clip. The general
detector often scores a real table at only 10-30% (seen from above, half hidden by
plates and people), which a single-frame threshold throws away.

Rule: group detections that overlap across frames into candidates, then accept a
candidate when EITHER
  - it was seen at least twice with a confident score (the original rule), OR
  - it was seen, at any score above the low floor, in at least a quarter of the
    sampled frames and at least 3 times (persistent weak evidence).
Accepted candidates that overlap each other are merged, keeping the best supported.
"""
from math import ceil

STRONG, WEAK = 0.23, 0.10           # detector scores
MIN_AREA, MAX_AREA = 0.004, 0.45    # share of the frame; rejects specks and "the whole room"
SAME_TABLE = 0.32


def overlap(a, b) -> float:
    intersection = max(0, min(a.x2, b.x2) - max(a.x1, b.x1)) * max(0, min(a.y2, b.y2) - max(a.y1, b.y1))
    area_a = (a.x2 - a.x1) * (a.y2 - a.y1)
    area_b = (b.x2 - b.x1) * (b.y2 - b.y1)
    union = area_a + area_b - intersection
    if min(area_a, area_b) <= 0:
        return 0
    # Partial occlusion can shrink a detection to a box inside the full table.
    return max(intersection / union, .65 * intersection / min(area_a, area_b))


class TableCandidates:
    def __init__(self):
        self.items: list[dict] = []   # {"box", "strong", "seen"}
        self.frames = 0

    def add_frame(self, boxes):
        """boxes: table detections of one sampled frame, any score >= WEAK."""
        self.frames += 1
        matched = set()
        for box in sorted(boxes, key=lambda b: -b.conf):  # confident boxes claim candidates first
            area = (box.x2 - box.x1) * (box.y2 - box.y1)
            if box.conf < WEAK or not MIN_AREA <= area <= MAX_AREA:
                continue
            best = max(range(len(self.items)), key=lambda i: overlap(box, self.items[i]["box"]), default=None)
            if best is not None and overlap(box, self.items[best]["box"]) >= SAME_TABLE:
                if best in matched:
                    continue
                item = self.items[best]
                if box.conf > item["box"].conf:
                    item["box"] = box
                item["seen"] += 1
                item["strong"] += box.conf >= STRONG
                matched.add(best)
            else:
                matched.add(len(self.items))
                self.items.append({"box": box, "seen": 1, "strong": int(box.conf >= STRONG)})

    def accepted(self):
        need_strong = min(2, self.frames)
        need_seen = max(3, ceil(0.25 * self.frames))
        good = [c for c in self.items if c["strong"] >= need_strong or c["seen"] >= need_seen]
        good.sort(key=lambda c: (-c["strong"], -c["seen"], -c["box"].conf))
        kept = []
        for c in good:
            if all(overlap(c["box"], k["box"]) < SAME_TABLE for k in kept):
                kept.append(c)
        return sorted((c["box"] for c in kept), key=lambda b: (b.y1 + b.y2, b.x1 + b.x2))
