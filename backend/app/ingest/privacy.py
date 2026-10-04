"""Privacy masking: hide track start/end and user-defined zones (home, work...).

Raw tracks stay untouched (map-matching needs them); masking is applied to
anything that leaves the user's hands (export, display, community sharing).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .models import Activity, TrackPoint, haversine

DEFAULT_TRIM_M = 200.0


@dataclass(frozen=True)
class PrivacyZone:
    lat: float
    lon: float
    radius_m: float = 300.0
    name: str | None = None

    def contains(self, p: TrackPoint) -> bool:
        return haversine(TrackPoint(None, self.lat, self.lon), p) <= self.radius_m


def load_zones(path: str | Path) -> list[PrivacyZone]:
    """Read `[{"lat":..,"lon":..,"radius_m":..,"name":..}, ...]` (keep this file in data/)."""
    return [PrivacyZone(**z) for z in json.loads(Path(path).read_text(encoding="utf-8"))]


def mask(act: Activity, zones: list[PrivacyZone] = (), trim_m: float = DEFAULT_TRIM_M) -> list[list[TrackPoint]]:
    """Return the visible segments of `act`: start/end trimmed, points inside zones removed.

    The track is split where it crosses a zone so no line is drawn through it.
    """
    pts = act.points
    lo, hi = _trim_index(pts, trim_m), len(pts) - _trim_index(pts[::-1], trim_m)
    segments: list[list[TrackPoint]] = []
    current: list[TrackPoint] = []
    for p in pts[lo:hi]:
        if any(z.contains(p) for z in zones):
            if current:
                segments.append(current)
            current = []
        else:
            current.append(p)
    if current:
        segments.append(current)
    return [s for s in segments if len(s) >= 2]


def _trim_index(pts: list[TrackPoint], trim_m: float) -> int:
    """Index of the first point farther than `trim_m` (straight line) from the track's first point.

    Straight-line rather than along-track distance: a track winding around its
    start would otherwise reveal points close to it.
    """
    if trim_m <= 0 or not pts:
        return 0
    for i, p in enumerate(pts):
        if haversine(pts[0], p) > trim_m:
            return i
    return len(pts)
