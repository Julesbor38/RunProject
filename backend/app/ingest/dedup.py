"""Merge duplicates: the same run is often both in the Strava export and as a Coros .fit."""
from __future__ import annotations

from .models import Activity

START_TOLERANCE_S = 180
DISTANCE_TOLERANCE = 0.10


def is_duplicate(a: Activity, b: Activity) -> bool:
    if not (a.start and b.start):
        return False
    if abs((a.start - b.start).total_seconds()) > START_TOLERANCE_S:
        return False
    da, db = a.distance_m, b.distance_m
    return abs(da - db) <= DISTANCE_TOLERANCE * max(da, db, 1)


def dedupe(acts: list[Activity]) -> tuple[list[Activity], int]:
    """Keep the densest track of each duplicate group, borrowing a missing name. Returns (kept, n_dropped)."""
    ordered = sorted(acts, key=lambda a: (a.start is None, a.start))
    kept: list[Activity] = []
    dropped = 0
    for act in ordered:
        # Only recent kept activities can match since the list is sorted by start.
        match = next((k for k in reversed(kept[-5:]) if is_duplicate(k, act)), None)
        if match is None:
            kept.append(act)
            continue
        dropped += 1
        best, other = (act, match) if len(act.points) > len(match.points) else (match, act)
        best.name = best.name or other.name
        if best.sport in (None, "run") and other.sport == "trail_run":
            best.sport = "trail_run"
        kept[kept.index(match)] = best
    return kept, dropped
