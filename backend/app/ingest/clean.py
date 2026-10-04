"""Track cleaning: drop GPS spikes and redundant points."""
from __future__ import annotations

from dataclasses import replace

from .models import Activity, TrackPoint, haversine

MAX_SPEED_MPS = 12.0   # ~2:20/km, well above any running pace
MIN_STEP_M = 1.0       # points closer than this to the previous one are redundant


def clean(act: Activity, max_speed_mps: float = MAX_SPEED_MPS, min_step_m: float = MIN_STEP_M) -> Activity:
    """Return a copy of `act` without out-of-order points, spikes and near-duplicates."""
    pts = [p for p in act.points if -90 <= p.lat <= 90 and -180 <= p.lon <= 180 and (p.lat, p.lon) != (0, 0)]
    if all(p.time for p in pts):
        pts.sort(key=lambda p: p.time)

    kept: list[TrackPoint] = []
    for p in pts:
        if not kept:
            kept.append(p)
            continue
        prev = kept[-1]
        d = haversine(prev, p)
        if d < min_step_m:
            continue
        if prev.time and p.time:
            dt = (p.time - prev.time).total_seconds()
            if dt <= 0 or d / dt > max_speed_mps:
                continue
        kept.append(p)
    return replace(act, points=kept)
