"""COCO tableware evidence assigned to detected surfaces, then to configured tables."""

TABLEWARE_CLASSES = (40, 41, 42, 43, 44, 45)  # wine glass, cup, fork, knife, spoon, bowl


def counts_by_surface(surfaces, items):
    counts = [0] * len(surfaces)
    for item in items:
        x, y = (item.x1 + item.x2) / 2, (item.y1 + item.y2) / 2
        matches = [((s.x2 - s.x1) * (s.y2 - s.y1), i) for i, s in enumerate(surfaces)
                   if s.x1 <= x <= s.x2 and s.y1 <= y <= s.y2]
        if matches:
            counts[min(matches)[1]] += 1
    return counts
