from datetime import datetime, timedelta, timezone

from app.ingest import Activity, PrivacyZone, TrackPoint, clean, dedupe, mask
from app.ingest.models import haversine
from app.ingest.simplify import simplify

T0 = datetime(2026, 10, 3, 13, 44, tzinfo=timezone.utc)
STEP = 0.0001  # ~11 m of latitude


def track(n: int, start: datetime = T0, lat0: float = 45.0, source: str = "x") -> Activity:
    """Straight northward run, one point every 4 s (~2.8 m/s)."""
    pts = [TrackPoint(start + timedelta(seconds=4 * i), lat0 + i * STEP, 4.65) for i in range(n)]
    return Activity(source=source, sport="run", start=start, points=pts)


def test_clean_drops_spike_and_duplicate():
    a = track(10)
    spike = TrackPoint(a.points[4].time + timedelta(seconds=1), 45.5, 4.65)
    dup = TrackPoint(a.points[6].time + timedelta(seconds=1), a.points[6].lat, a.points[6].lon)
    a.points[5:5] = [spike]
    a.points[8:8] = [dup]
    c = clean(a)
    assert c.points == track(10).points
    assert len(a.points) == 12  # original untouched


def test_clean_reorders_by_time():
    a = track(5)
    a.points.reverse()
    assert clean(a).points == track(5).points


def test_dedupe_keeps_densest_and_merges_metadata():
    strava = track(50, source="strava:1")
    strava.name, strava.sport = "Sortie trail", "trail_run"
    strava.points = strava.points[::2]
    coros = track(50, start=T0 + timedelta(seconds=30), source="coros.fit")
    other_day = track(50, start=T0 + timedelta(days=1))
    kept, dropped = dedupe([strava, other_day, coros])
    assert dropped == 1 and len(kept) == 2
    assert kept[0].source == "coros.fit"
    assert kept[0].name == "Sortie trail" and kept[0].sport == "trail_run"


def test_dedupe_keeps_same_start_different_distance():
    kept, dropped = dedupe([track(50), track(200)])
    assert dropped == 0 and len(kept) == 2


def test_mask_trims_start_and_end():
    a = track(100)  # ~1.1 km
    segs = mask(a, trim_m=200)
    assert len(segs) == 1
    assert haversine(a.points[0], segs[0][0]) > 200
    assert haversine(a.points[-1], segs[0][-1]) > 200


def test_mask_splits_around_zone():
    a = track(100)
    mid = a.points[50]
    segs = mask(a, [PrivacyZone(mid.lat, mid.lon, 100)], trim_m=0)
    assert len(segs) == 2
    for s in segs:
        assert all(haversine(mid, p) > 100 for p in s)


def test_masked_geojson_is_multilinestring():
    a = track(100)
    f = a.to_geojson(mask(a))
    assert f["geometry"]["type"] == "MultiLineString"
    assert f["properties"]["distance_m"] == round(a.distance_m)


def test_simplify_straight_line_keeps_ends():
    a = track(50)
    kept = simplify(a.points, 5.0)
    assert kept == [a.points[0], a.points[-1]]


def test_simplify_keeps_corner():
    a = track(10)
    corner = a.points[-1]
    a.points += [TrackPoint(None, corner.lat, corner.lon + i * STEP) for i in range(1, 10)]
    assert corner in simplify(a.points, 5.0)
