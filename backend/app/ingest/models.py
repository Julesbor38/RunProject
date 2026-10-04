"""Normalized activity model, independent of the source format."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TrackPoint:
    time: datetime | None
    lat: float
    lon: float
    ele: float | None = None
    hr: int | None = None


@dataclass
class Activity:
    source: str                      # file path or Strava id
    sport: str | None = None         # normalized: "run", "trail_run", "other"...
    name: str | None = None
    start: datetime | None = None
    points: list[TrackPoint] = field(default_factory=list)

    @property
    def has_gps(self) -> bool:
        return len(self.points) >= 2

    @property
    def distance_m(self) -> float:
        return sum(haversine(a, b) for a, b in zip(self.points, self.points[1:]))

    @property
    def ascent_m(self) -> float:
        """Ascent with a 3 m hysteresis to filter altitude noise."""
        total, ref = 0.0, None
        for p in self.points:
            if p.ele is None:
                continue
            if ref is None:
                ref = p.ele
            elif p.ele - ref >= 3:
                total += p.ele - ref
                ref = p.ele
            elif p.ele < ref:
                ref = p.ele
        return total

    @property
    def duration_s(self) -> float | None:
        times = [p.time for p in self.points if p.time]
        return (times[-1] - times[0]).total_seconds() if len(times) >= 2 else None

    def to_geojson(self) -> dict:
        return {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [
                    [p.lon, p.lat] + ([p.ele] if p.ele is not None else []) for p in self.points
                ],
            },
            "properties": {
                "source": self.source,
                "sport": self.sport,
                "name": self.name,
                "start": self.start.isoformat() if self.start else None,
                "distance_m": round(self.distance_m),
                "ascent_m": round(self.ascent_m),
            },
        }


def haversine(a: TrackPoint, b: TrackPoint) -> float:
    r = 6_371_000
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp, dl = p2 - p1, math.radians(b.lon - a.lon)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))
