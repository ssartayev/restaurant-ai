"""Geometry: which table does a detected person belong to?

All coordinates are normalised to 0..1 of the frame, so zones survive a resolution change.
A person is reduced to ONE anchor point; a table is occupied by that person if the
point lies inside any of the table's seat polygons.
"""
from dataclasses import dataclass

Point = tuple[float, float]
Polygon = list[Point]


@dataclass(frozen=True)
class Box:
    """Person bounding box, normalised. (x1, y1) top-left, (x2, y2) bottom-right."""
    x1: float
    y1: float
    x2: float
    y2: float
    conf: float = 1.0


@dataclass(frozen=True)
class TableZone:
    table_id: str
    polygons: list[Polygon]
    label: str = ""


def anchor_point(box: Box, ax: float = 0.5, ay: float = 0.75) -> Point:
    """Point that represents where the person IS.

    Default: horizontally centred, 75% of the way down the box. For a seated person
    that is around the hips/chair, which stays inside the seat zone even when the
    head and shoulders overlap a neighbouring table in the image. The bottom edge
    (ay=1.0) is worse for seated people because the table often hides their legs.
    """
    return (box.x1 + ax * (box.x2 - box.x1), box.y1 + ay * (box.y2 - box.y1))


def point_in_polygon(p: Point, poly: Polygon) -> bool:
    """Ray casting: count how many edges a horizontal ray from p crosses. Odd = inside."""
    x, y = p
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):  # edge straddles the ray's height
            x_cross = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < x_cross:
                inside = not inside
    return inside


def count_people(boxes: list[Box], zones: list[TableZone], *, min_conf: float = 0.35,
                 ax: float = 0.5, ay: float = 0.75) -> dict[str, int]:
    """People per table. A person counts for at most one table (first matching zone)."""
    counts = {z.table_id: 0 for z in zones}
    for box in boxes:
        if box.conf < min_conf:
            continue
        p = anchor_point(box, ax, ay)
        for z in zones:
            if any(point_in_polygon(p, poly) for poly in z.polygons):
                counts[z.table_id] += 1
                break
    return counts
