"""Track simplification (Douglas-Peucker) to keep map payloads light."""
from __future__ import annotations

import math

from .models import TrackPoint


def simplify(points: list[TrackPoint], tolerance_m: float) -> list[TrackPoint]:
    """Drop points closer than `tolerance_m` to the line joining their neighbours. Ends are kept."""
    if len(points) < 3:
        return list(points)
    # Local equirectangular projection: accurate enough at track scale.
    lat0 = math.radians(points[0].lat)
    xy = [(math.radians(p.lon) * math.cos(lat0) * 6_371_000, math.radians(p.lat) * 6_371_000) for p in points]
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        lo, hi = stack.pop()
        best, idx = 0.0, -1
        for i in range(lo + 1, hi):
            d = _segment_distance(xy[i], xy[lo], xy[hi])
            if d > best:
                best, idx = d, i
        if idx != -1 and best > tolerance_m:
            keep[idx] = True
            stack += [(lo, idx), (idx, hi)]
    return [p for p, k in zip(points, keep) if k]


def _segment_distance(p, a, b) -> float:
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    if dx == dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)
