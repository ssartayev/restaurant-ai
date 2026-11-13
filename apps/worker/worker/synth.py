"""Synthetic detection traces with ground truth.

Stands in for labelled video until staged recordings exist. It produces what a person
detector would output (boxes per sampled frame) for a scripted service, with the
failure modes the filter must survive: missed detections, guests standing briefly,
staff walking through zones, staff clearing a table after a party leaves, staff
setting a ready table, and a solo diner stepping away.

IMPORTANT: numbers measured on these traces show that the LOGIC behaves as designed.
They say nothing about detector accuracy on real footage.
"""
import random

from .zones import TableZone


def grid_zones(n: int = 6) -> list[TableZone]:
    zones = []
    for i in range(n):
        cx, cy = 0.2 + 0.3 * (i % 3), 0.3 + 0.4 * (i // 3)
        zones.append(TableZone(f"tbl_{i + 1}", [[(cx - 0.1, cy - 0.12), (cx + 0.1, cy - 0.12),
                                                  (cx + 0.1, cy + 0.12), (cx - 0.1, cy + 0.12)]],
                               label=f"T{i + 1}"))
    return zones


def _centre(zone: TableZone):
    xs = [p[0] for p in zone.polygons[0]]
    ys = [p[1] for p in zone.polygons[0]]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def _person_box(cx, cy, rng, conf=None):
    """A box whose anchor point (50%, 75%) lands near (cx, cy)."""
    w, h = 0.05, 0.16
    cx += rng.uniform(-0.03, 0.03)
    cy += rng.uniform(-0.03, 0.03)
    return [round(cx - w / 2, 4), round(cy - 0.75 * h, 4), round(cx + w / 2, 4),
            round(cy + 0.25 * h, 4), round(conf if conf is not None else rng.uniform(0.5, 0.95), 3)]


def generate(seed: int, *, duration_s: int = 3600, fps: float = 2.0, n_tables: int = 6,
             miss_rate: float = 0.12, tags: tuple[str, ...] = ()) -> dict:
    """Returns {"zones", "frames", "labels", "duration_s", "table_hours", "tags"}.

    tags switch on harder behaviour: "staff_pass", "brief_stand", "clearing",
    "solo_absence", "low_light" (higher miss rate, lower confidence), "table_setting".
    """
    rng = random.Random(seed)
    zones = grid_zones(n_tables)
    if "low_light" in tags:
        miss_rate = 0.3
    # --- script the parties: [arrive, leave) intervals per table ---
    presence = {z.table_id: [] for z in zones}   # (start, end, size, absences[(a, b)])
    labels = []
    for z in zones:
        t = rng.uniform(30, 400)
        while t < duration_s - 900:
            size = rng.choice([1, 2, 2, 2, 3, 4])
            stay = rng.uniform(420, 1200)
            leave = t + stay
            if leave > duration_s - 300:
                break  # the departure must be observable before the trace ends
            absences = []
            if "brief_stand" in tags and rng.random() < 0.7:
                a = rng.uniform(t + 60, leave - 120)
                absences.append((a, a + rng.uniform(15, 45), "all" if size == 1 else "one"))
            if "solo_absence" in tags and size == 1 and rng.random() < 0.6:
                a = rng.uniform(t + 60, leave - 300)
                absences.append((a, a + rng.uniform(120, 200), "all"))
            presence[z.table_id].append((t, leave, size, absences))
            labels.append({"table_id": z.table_id, "type": "party_seated", "t": round(t, 1)})
            labels.append({"table_id": z.table_id, "type": "party_left", "t": round(leave, 1)})
            t = leave + rng.uniform(240, 600)

    # --- staff behaviour: (start, end, table_id) intervals where a staff member is in the zone ---
    staff = []
    if "staff_pass" in tags:
        for _ in range(int(duration_s / 60)):
            a = rng.uniform(0, duration_s)
            staff.append((a, a + rng.uniform(2, 6), rng.choice(zones).table_id))
    ready_at = {}  # (table_id, leave) -> when staff finished resetting the table
    for tid, parties in presence.items():
        for _, leave, _, _ in parties:
            if "clearing" in tags:
                a = leave + rng.uniform(20, 90)
                b = a + rng.uniform(20, 50)
                staff.append((a, b, tid))
                ready_at[(tid, leave)] = b + 5
            else:
                ready_at[(tid, leave)] = leave + rng.uniform(100, 140)
            labels.append({"table_id": tid, "type": "table_ready", "t": round(ready_at[(tid, leave)], 1)})
    if "table_setting" in tags:
        for tid, parties in presence.items():
            for _, leave, _, _ in parties:
                a = leave + rng.uniform(150, 220)
                staff.append((a, a + rng.uniform(8, 16), tid))

    # --- render frames ---
    frames = []
    centres = {z.table_id: _centre(z) for z in zones}
    steps = int(duration_s * fps)
    for i in range(steps):
        t = i / fps
        boxes = []
        for tid, parties in presence.items():
            cx, cy = centres[tid]
            for start, end, size, absences in parties:
                if not (start <= t < end):
                    continue
                away = [kind for a, b, kind in absences if a <= t < b]
                seated = 0 if "all" in away else size - (1 if "one" in away else 0)
                for k in range(seated):
                    if rng.random() < miss_rate:
                        continue  # the detector missed this person in this frame
                    conf = rng.uniform(0.36, 0.7) if "low_light" in tags else None
                    boxes.append(_person_box(cx + (k - size / 2) * 0.03, cy, rng, conf))
        for a, b, tid in staff:
            if a <= t < b:
                cx, cy = centres[tid]
                boxes.append(_person_box(cx, cy, rng))
        frames.append({"t": round(t, 3), "boxes": boxes})

    return {"zones": [{"table_id": z.table_id, "label": z.label,
                       "polygons": [[list(p) for p in poly] for poly in z.polygons]} for z in zones],
            "frames": frames, "labels": labels, "duration_s": duration_s,
            "table_hours": round(n_tables * duration_s / 3600, 3), "tags": list(tags)}
