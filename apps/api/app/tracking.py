"""Short-term person tracking for one recording. Never identity recognition.

Why this exists: a waiter mark has to follow one person through the clip. Matching
1-second samples in the browser lost a walking person almost at once, because a person
walks close to their own height per second, similar clothing nearby looked "ambiguous",
and one ambiguous frame ended the mark for good.

Method (tracking by detection):
  1. Run on every tracked frame (several per second), so a person moves only a
     fraction of their height between frames and overlap is a strong cue.
  2. Score each detection against each live track from box overlap, centre distance
     (gate grows with the time since the track was seen) and clothing colour.
  3. Assign best pairs first. If two candidates are too close to call, neither is
     assigned: the track is NOT transferred to a stranger, it simply pauses.
  4. A paused or lost track can be resumed for a few seconds (stitching) when exactly
     one new detection fits in position and clothing.

Track numbers are local to one analysis. No face data, no descriptor leaves this
module except the clothing histogram already returned for display.
"""
from dataclasses import dataclass, field
from math import hypot

MAX_GAP_S = 1.2        # a live track may miss detections for this long
STITCH_GAP_S = 8.0     # a lost track may be resumed within this time
GATE_BASE, GATE_PER_S, GATE_MAX = 0.45, 1.3, 3.5   # allowed movement, in body heights
MIN_APPEARANCE = 0.30  # frame-to-frame: geometry is strong, so clothing only vetoes
STITCH_APPEARANCE = 0.55
AMBIGUITY_MARGIN = 0.12


def iou(a, b) -> float:
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    inter = w * h
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


def similarity(a, b) -> float | None:
    """Histogram intersection of two clothing descriptors (1 = same colours)."""
    if not a or not b:
        return None
    return sum(min(x, y) for x, y in zip(a, b))


@dataclass
class Track:
    id: int
    box: tuple
    time: float
    appearance: list | None = None
    hits: int = 1
    velocity: tuple = (0.0, 0.0)
    history: list = field(default_factory=list)


def _centre(box):
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


class Tracker:
    def __init__(self):
        self.tracks: list[Track] = []
        self._next = 1

    def _score(self, track: Track, box, appearance, time: float, *, stitching: bool):
        dt = max(time - track.time, 1e-3)
        height = max(0.04, box[3] - box[1], track.box[3] - track.box[1])
        cx, cy = _centre(track.box)
        if not stitching:  # constant-velocity prediction for short steps only
            cx, cy = cx + track.velocity[0] * dt, cy + track.velocity[1] * dt
        x, y = _centre(box)
        distance = hypot(x - cx, y - cy) / height
        gate = min(GATE_MAX, GATE_BASE + GATE_PER_S * dt)
        if distance > gate:
            return None
        sim = similarity(track.appearance, appearance)
        if sim is not None and sim < (STITCH_APPEARANCE if stitching else MIN_APPEARANCE):
            return None
        if stitching and sim is None:
            return None  # never resume a lost track on position alone
        overlap = 0.0 if stitching else iou(track.box, box)
        return overlap + 0.6 * (1 - distance / gate) + 0.8 * (sim if sim is not None else 0.5)

    def update(self, time: float, boxes: list[tuple], appearances: list) -> list[int]:
        """Returns one track number per box, in the same order."""
        live = [t for t in self.tracks if time - t.time <= MAX_GAP_S]
        lost = [t for t in self.tracks if MAX_GAP_S < time - t.time <= STITCH_GAP_S]
        self.tracks = live + lost
        assigned: dict[int, Track] = {}
        used: set[int] = set()
        unclear: set[int] = set()   # boxes we could not attribute to one person on this frame

        for pool, stitching in ((live, False), (lost, True)):
            pairs = []
            for i, (box, appearance) in enumerate(zip(boxes, appearances)):
                if i in assigned:
                    continue
                for track in pool:
                    if track.id in used:
                        continue
                    score = self._score(track, box, appearance, time, stitching=stitching)
                    if score is not None:
                        pairs.append((score, i, track))
            pairs.sort(key=lambda p: -p[0])
            best_track, best_box = {}, {}
            for score, i, track in pairs:           # pairs are in descending score order
                best_track.setdefault(i, track.id)
                best_box.setdefault(track.id, i)
            blocked_boxes, blocked_tracks = set(), set()
            for score, i, track in pairs:
                if i in assigned or track.id in used or i in blocked_boxes or track.id in blocked_tracks:
                    continue
                # Two detections that both fit this track best, about equally well:
                # we cannot tell who continues it, so the track pauses instead of jumping.
                if any(t.id == track.id and j != i and j not in assigned and best_track[j] == track.id
                       and score - s < AMBIGUITY_MARGIN for s, j, t in pairs):
                    blocked_tracks.add(track.id)
                    unclear.update(j for s, j, t in pairs if t.id == track.id and score - s < AMBIGUITY_MARGIN)
                    continue
                # One detection that fits two tracks about equally well (two people merged
                # into one box): neither track takes it.
                if any(j == i and t.id != track.id and t.id not in used and best_box[t.id] == i
                       and score - s < AMBIGUITY_MARGIN for s, j, t in pairs):
                    blocked_boxes.add(i)
                    unclear.add(i)
                    continue
                assigned[i] = track
                used.add(track.id)

        ids = []
        for i, (box, appearance) in enumerate(zip(boxes, appearances)):
            track = assigned.get(i)
            if track is None and i in unclear:
                # A merged or contested box gets a throwaway number and starts no track, so
                # the real people can pick their own tracks up again once they separate.
                ids.append(self._next)
                self._next += 1
                continue
            if track is None:
                track = Track(self._next, box, time, list(appearance) if appearance else None, hits=0)
                self._next += 1
                self.tracks.append(track)
            else:
                dt = max(time - track.time, 1e-3)
                (ox, oy), (nx, ny) = _centre(track.box), _centre(box)
                if dt <= MAX_GAP_S:
                    track.velocity = (0.5 * track.velocity[0] + 0.5 * (nx - ox) / dt,
                                      0.5 * track.velocity[1] + 0.5 * (ny - oy) / dt)
                else:
                    track.velocity = (0.0, 0.0)
                if appearance and not track.appearance:
                    track.appearance = list(appearance)
                elif appearance:
                    # Learn the clothing only from crops that clearly show this person. When two
                    # people overlap, the merged crop looks like a mix; learning from it would
                    # slowly turn this track into the other person.
                    sim = similarity(track.appearance, appearance)
                    rate = 0.15 if sim >= 0.7 else 0.03 if sim >= 0.5 else 0.0
                    if rate:
                        track.appearance = [(1 - rate) * a + rate * b for a, b in zip(track.appearance, appearance)]
            track.box, track.time, track.hits = box, time, track.hits + 1
            ids.append(track.id)
        return ids
