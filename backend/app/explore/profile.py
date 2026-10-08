"""Running profile of an activity, from its visible parts (masked, <= 25 km/h): km run, D+, km at night
(sun below -6°: dusk to dawn) and km faster than 5:00/km. Summed over a familier's life, it decides the
branch of its final form (app/game/pets.py)."""
from __future__ import annotations

import math
from datetime import datetime, timezone

from ..ingest.models import TrackPoint, haversine

ASCENT_THRESHOLD_M = 3.0  # hysteresis: GPS / barometric noise below this does not count as climbing
FAST_MS = 1000 / 300  # 5:00/km
NIGHT_SUN_DEG = -6.0  # civil twilight
_J2000 = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)


def sun_elevation(lat: float, lon: float, t: datetime) -> float:
    """Elevation of the sun in degrees (low-precision formula, ~0.5°: plenty to tell night from day)."""
    d = ((t if t.tzinfo else t.replace(tzinfo=timezone.utc)) - _J2000).total_seconds() / 86400
    g = math.radians(357.529 + 0.98560028 * d)
    q = 280.459 + 0.98564736 * d
    ecl_lon = math.radians(q + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g))
    eps = math.radians(23.439 - 0.00000036 * d)
    ra = math.atan2(math.cos(eps) * math.sin(ecl_lon), math.cos(ecl_lon))
    dec = math.asin(math.sin(eps) * math.sin(ecl_lon))
    gmst = (18.697374558 + 24.06570982441908 * d) % 24
    ha = math.radians(gmst * 15 + lon) - ra
    la = math.radians(lat)
    return math.degrees(math.asin(math.sin(la) * math.sin(dec) + math.cos(la) * math.cos(dec) * math.cos(ha)))


def profile(parts: list[list[TrackPoint]]) -> dict:
    """{run_m, ascent_m, night_m, fast_m} of the visible parts of an activity."""
    run = ascent = night = fast = 0.0
    night_cache: dict[int, bool] = {}  # per 5 minutes: the sun barely moves
    for part in parts:
        ref = None
        for a, b in zip(part, part[1:]):
            d = haversine(a, b)
            run += d
            if a.time and b.time:
                dt = (b.time - a.time).total_seconds()
                if dt > 0 and d / dt >= FAST_MS:
                    fast += d
                slot = int(a.time.timestamp() // 300)
                if slot not in night_cache:
                    night_cache[slot] = sun_elevation(a.lat, a.lon, a.time) < NIGHT_SUN_DEG
                if night_cache[slot]:
                    night += d
            for p in (a, b) if ref is None else (b,):
                if p.ele is None:
                    continue
                if ref is None:
                    ref = p.ele
                elif p.ele > ref + ASCENT_THRESHOLD_M:
                    ascent += p.ele - ref
                    ref = p.ele
                elif p.ele < ref - ASCENT_THRESHOLD_M:
                    ref = p.ele
    return {"run_m": run, "ascent_m": ascent, "night_m": night, "fast_m": fast}
