import math
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest

from app.explore.area import cell_area, cell_center, corridor_cells, in_polygons, polygons_area, veil
from app.explore.communes import walkable_total
from app.explore.explorer import Explorer
from app.explore.matching import EdgeIndex, moving_parts, segment_key, traversed_edges
from app.explore.store import Commune, ExploreStore
from app.ingest.models import Activity, TrackPoint
from app.ingest.privacy import PrivacyZone, mask
from app.pois.store import Poi, PoiStore
from app.routing.graph import build_graph

from test_routing import LAT0, LON0, STEP, grid

LON_STEP = STEP * 1.43
T0 = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)


def node(i, j):
    return LAT0 + i * STEP, LON0 + j * LON_STEP


def track(path, speed_ms=3.0, start=T0, every_m=8.0, timed=True):
    """Track points every `every_m` along the (i, j) grid nodes, at `speed_ms`."""
    pts, t = [], 0.0
    corners = [node(*p) for p in path]
    for (alat, alon), (blat, blon) in zip(corners, corners[1:]):
        k = 111_320 * math.cos(math.radians(alat))
        seg = math.hypot((blon - alon) * k, (blat - alat) * 111_320)
        n = max(1, int(seg / every_m))
        for s in range(n):
            f = s / n
            pts.append(TrackPoint(start + timedelta(seconds=t) if timed else None, alat + f * (blat - alat), alon + f * (blon - alon)))
            t += seg / n / speed_ms
    lat, lon = corners[-1]
    pts.append(TrackPoint(start + timedelta(seconds=t) if timed else None, lat, lon))
    return pts


@pytest.fixture(scope="module")
def g():
    return build_graph(grid())


def keys(g, edges):
    return {segment_key(g.edges[i].nodes) for i in edges}


def edge_key(g, a, b):
    """Key of the grid edge between nodes a and b (ids i*100+j)."""
    for e in g.edges:
        if {e.u, e.v} == {a, b}:
            return segment_key(e.nodes)
    raise KeyError((a, b))


def test_run_along_a_street_traverses_its_segments_not_the_side_streets(g):
    found = keys(g, traversed_edges(g, [track([(5, 0), (5, 5)])]))
    assert found == {edge_key(g, 500 + j, 501 + j) for j in range(5)}


def test_touching_a_segment_is_not_traversing_it(g):
    # 0 -> 3 along row 5, then 60 m up column 3 (of a 200 m segment) and back down
    up = (5 + 60 / 200, 3)
    found = keys(g, traversed_edges(g, [track([(5, 0), (5, 3), up, (5, 3)])]))
    assert edge_key(g, 503, 603) not in found
    assert edge_key(g, 502, 503) in found


def test_out_and_back_counts_once(g):
    there_and_back = traversed_edges(g, [track([(5, 0), (5, 3), (5, 0)])])
    assert keys(g, there_and_back) == {edge_key(g, 500, 501), edge_key(g, 501, 502), edge_key(g, 502, 503)}


def test_bike_speed_portion_is_ignored(g):
    run = track([(5, 0), (5, 2)])
    bike = track([(5, 2), (5, 5)], speed_ms=10, start=run[-1].time + timedelta(seconds=1))  # 36 km/h
    run2 = track([(5, 5), (6, 5)], start=bike[-1].time + timedelta(seconds=1))
    parts = moving_parts([run + bike[1:] + run2[1:]])
    found = keys(g, traversed_edges(g, parts))
    assert edge_key(g, 500, 501) in found and edge_key(g, 505, 605) in found
    assert edge_key(g, 503, 504) not in found


def test_privacy_zone_is_excluded(g):
    act = Activity("strava:1", "run", "x", T0, track([(5, 0), (5, 8)]))
    lat, lon = node(5, 4)
    parts = moving_parts(mask(act, [PrivacyZone(lat, lon, 250)], trim_m=0))
    found = keys(g, traversed_edges(g, parts))
    assert edge_key(g, 500, 501) in found and edge_key(g, 507, 508) in found
    assert edge_key(g, 503, 504) not in found and edge_key(g, 504, 505) not in found


def explorer(tmp_path, g, pois=None):
    ex = Explorer(ExploreStore(tmp_path / "explore.sqlite"), tmp_path / "osm", pois)
    ex._graph_for = lambda parts: (g, EdgeIndex(g))
    return ex


def test_untimed_activity_is_not_counted(tmp_path, g):
    ex = explorer(tmp_path, g)
    planned = Activity("file:plan.gpx", "run", "plan", T0, track([(5, 0), (5, 5)], timed=False))
    timed = Activity("strava:2", "run", "run", T0, track([(4, 0), (4, 5)]))
    ex.process("jules", tmp_path, lambda s: s, [planned, timed])
    # only the timed one; its first and last 200 m are masked (privacy), so 3 of its 5 segments
    assert ex.store.totals("jules")["segments"] == 3
    assert ex.store.processed("jules") == {"file:plan.gpx", "strava:2"}  # both done, never retried
    assert ex.process("jules", tmp_path, lambda s: s, [planned, timed]) == 0  # incremental


def test_commune_percentage(tmp_path, g):
    ex = explorer(tmp_path, g)
    # the lower half of the grid (rows 0-4 and half of the segments to row 5)
    lat_mid = LAT0 + 4.5 * STEP
    ring = [[LON0 - 0.001, LAT0 - 0.001], [LON0 + 10 * LON_STEP + 0.001, LAT0 - 0.001], [LON0 + 10 * LON_STEP + 0.001, lat_mid], [LON0 - 0.001, lat_mid]]
    c = Commune("69999", "Testville", "69999", [[ring]], None, (ring[0][0], ring[0][1], ring[2][0], ring[2][1]))
    ex.store.add_communes([c])
    total = walkable_total(c, tmp_path / "osm", graph=g)
    assert total == pytest.approx(10 * 5 * 200 + 11 * 4 * 200, rel=0.01)  # 5 rows of 10 segments, 11 columns of 4
    ex.store.set_total("69999", total)
    ex.process("jules", tmp_path, lambda s: s, [Activity("strava:3", "run", "r", T0, track([(2, 0), (2, 10)]))])
    town = ex.summary("jules")["communes"][0]
    # 2 km along row 2, minus the 200 m masked at each end
    assert town["name"] == "Testville" and town["done_m"] == pytest.approx(1600, rel=0.02)
    assert town["pct"] == pytest.approx(100 * 1600 / total, abs=0.2)
    # area: a 100 m wide corridor along the 1600 m run, with round ends
    assert town["area_done_m2"] == pytest.approx(1600 * 100 + math.pi * 50**2, rel=0.03)
    assert town["area_m2"] == pytest.approx(polygons_area([[ring]]))
    assert town["area_pct"] == pytest.approx(100 * town["area_done_m2"] / town["area_m2"], abs=0.05)
    assert ex.store.totals("jules")["area_m2"] == town["area_done_m2"]


def test_place_discovered_within_30_m(tmp_path, g):
    pois = PoiStore(tmp_path / "pois.sqlite")
    lat, lon = node(5, 2)
    pois.add([
        Poi("n1", lat + 20 / 111_320, lon, "nature", "viewpoint", "Belvédère", 30, 12),  # 20 m from the street
        Poi("n2", lat + 60 / 111_320, lon, "nature", "peak", "Pic", 40, 12),  # 60 m
    ])
    ex = explorer(tmp_path, g, pois)
    ex.process("jules", tmp_path, lambda s: s, [Activity("strava:4", "run", "r", T0, track([(5, 0), (5, 5)]))])
    found = ex.store.discovered("jules")
    assert [p["poi"] for p in found] == ["n1"] and found[0]["first_date"].startswith("2026-10-01")
    # an earlier run of the same place keeps the earliest date
    earlier = T0 - timedelta(days=30)
    ex.process("jules", tmp_path, lambda s: s, [Activity("strava:5", "run", "r", earlier, track([(5, 0), (5, 5)], start=earlier))])
    assert ex.store.discovered("jules")[0]["first_date"].startswith("2026-09-01")
    assert ex.store.discovered("marie") == []  # per user


def test_milestones_and_badges():
    communes = [{"id": "1", "name": "A", "pct": 55.0}, {"id": "2", "name": "B", "pct": 9.0}]
    found = [{"kind": "peak", "category": "nature"}, {"kind": "waterfall", "category": "water"}, {"kind": "castle", "category": "heritage"}]
    ach = {a["id"]: a for a in Explorer.achievements(communes, found)}
    assert {"commune:1:10", "commune:1:25", "commune:1:50"} <= set(ach) and "commune:1:75" not in ach and "commune:2:10" not in ach
    assert ach["badge:communes:1"]["achieved"] and not ach["badge:communes:5"]["achieved"]
    assert ach["badge:peaks:1"]["achieved"] and ach["badge:waterfalls:1"]["achieved"] and ach["badge:heritage:1"]["achieved"]
    assert not ach["badge:lakes:1"]["achieved"]


def test_sidewalks_do_not_count_and_snap_to_their_street():
    from app.routing.osm import OsmData

    lat0, lon0 = 45.0, 4.0
    k = 111_320 * math.cos(math.radians(lat0))
    nodes = {1: (lat0, lon0), 2: (lat0, lon0 + 400 / k), 3: (lat0 + 8 / 111_320, lon0), 4: (lat0 + 8 / 111_320, lon0 + 400 / k)}
    osm = OsmData(nodes, [([1, 2], {"highway": "residential"}), ([3, 4], {"highway": "footway", "footway": "sidewalk"})])
    g2 = build_graph(osm)
    run = [TrackPoint(T0 + timedelta(seconds=i * 3), lat0 + 9 / 111_320, lon0 + i * 8 / k) for i in range(51)]  # on the sidewalk
    found = traversed_edges(g2, [run])
    assert [g2.edges[i].way_tags.get("highway") for i in found] == ["residential"]
    assert walkable_total(Commune("x", "X", None, [[[[3.9, 44.9], [4.1, 44.9], [4.1, 45.1], [3.9, 45.1]]]], None, (3.9, 44.9, 4.1, 45.1)), Path("."), graph=g2) == pytest.approx(400, rel=0.01)


def test_catching_up_is_quiet(tmp_path, g):
    """Communes extracted after the history was processed: their milestones are not news."""
    ex = explorer(tmp_path, g)
    ex.process("jules", tmp_path, lambda s: s, [Activity("strava:10", "run", "r", T0, track([(2, 0), (2, 10)]))])
    ring = [[LON0 - 0.001, LAT0 - 0.001], [LON0 + 10 * LON_STEP + 0.001, LAT0 - 0.001], [LON0 + 10 * LON_STEP + 0.001, LAT0 + 2.5 * STEP], [LON0 - 0.001, LAT0 + 2.5 * STEP]]
    ex.store.add_communes([Commune("69998", "Petiteville", None, [[ring]], 5000, (ring[0][0], ring[0][1], ring[2][0], ring[2][1]))])
    ex.process("jules", tmp_path, lambda s: s, [])
    s = ex.summary("jules")
    assert any(a["id"] == "commune:69998:25" and a["achieved"] for a in s["achievements"]) and s["new"] == []


def test_history_is_quiet_then_new_milestones_are_announced(tmp_path, g):
    pois = PoiStore(tmp_path / "pois.sqlite")
    lat, lon = node(8, 2)
    pois.add([Poi("n9", lat + 10 / 111_320, lon, "nature", "peak", "Crêt", 40, 12)])
    ex = explorer(tmp_path, g, pois)
    ex.process("jules", tmp_path, lambda s: s, [Activity("strava:6", "run", "r", T0, track([(2, 0), (2, 5)]))])
    assert ex.summary("jules")["new"] == []  # the history: recorded, not celebrated
    later = T0 + timedelta(days=2)
    ex.process("jules", tmp_path, lambda s: s, [Activity("strava:7", "run", "r", later, track([(8, 0), (8, 5)], start=later))], announce=True)
    assert [a["id"] for a in ex.summary("jules")["new"]] == ["badge:peaks:1"]
    ex.store.mark_seen("jules", ["badge:peaks:1"])
    assert ex.summary("jules")["new"] == []


def test_explore_api_is_per_user(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app import api, auth
    from test_pipeline import make_data

    root = make_data(tmp_path)
    monkeypatch.setattr(api, "DATA_DIR", root)
    monkeypatch.setattr(auth, "SCRYPT", {"n": 2**10, "r": 8, "p": 1})
    ex = api.explorer()
    ex.store.add_activity("tester", "strava:1", [], [{"poi": "n1", "name": "Pic", "category": "nature", "kind": "peak", "first_date": "2026-10-01"}])
    with TestClient(api.app) as c:
        s = c.get("/api/explore").json()
        assert s["discovered"] == 1 and {"communes", "achievements", "suggestions", "totals"} <= s.keys()
        assert c.get("/api/explore/fog", params={"bbox": "4,45,5,46"}).status_code == 422  # zoom in first
        assert c.get("/api/explore/fog", params={"bbox": "4.0,45.0,4.01,45.01"}).json()["type"] == "FeatureCollection"
        assert c.get("/api/explore/communes/12345").status_code == 404
        assert c.get("/api/explore/veil", params={"bbox": "0,40,5,46"}).status_code == 422  # zoom in first
        v = c.get("/api/explore/veil", params={"bbox": "4.0,45.0,4.1,45.1", "zoom": 12}).json()
        assert v["geometry"]["coordinates"] == [[[[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]]]]  # nothing run here
        assert c.post("/api/explore/seen", json={"ids": ["badge:peaks:1"]}).json() == {"ok": True}
    assert ex.store.settings("tester")["seen"] == ["badge:peaks:1"] and ex.store.settings("marie")["seen"] == []
    assert ex.store.discovered("marie") == [] and ex.store.settings("marie")["leaderboard_opt_in"] is False


def area_of(cells):
    return sum(cell_area(cy) for _, cy in cells)


def test_area_is_a_corridor_50_m_each_side():
    cells = corridor_cells([track([(5, 0), (5, 5)])])  # 1 km
    assert area_of(cells) == pytest.approx(1000 * 100 + math.pi * 50**2, rel=0.03)
    lat, lon = node(5, 2)
    centers = {(round(la, 5), round(lo, 5)) for la, lo in (cell_center(*c) for c in cells)}
    def near(dy_m):  # is there a discovered cell centre ~dy_m north of the street?
        return any(abs(la - (lat + dy_m / 111_320)) < 6 / 111_320 and abs(lo - lon) < 6 / 78_000 for la, lo in centers)
    assert near(0) and near(45) and not near(60)


def test_area_out_and_back_counts_once():
    one_way = corridor_cells([track([(5, 0), (5, 3)])])
    there_and_back = corridor_cells([track([(5, 0), (5, 3), (5, 0)])])
    assert there_and_back == one_way


def test_area_is_added_only_once_across_activities(tmp_path, g):
    ex = explorer(tmp_path, g)
    a1 = Activity("strava:8", "run", "r", T0, track([(2, 0), (2, 6)]))
    a2 = Activity("strava:9", "run", "r", T0 + timedelta(days=1), track([(2, 0), (2, 6)], start=T0 + timedelta(days=1)))
    ex.process("jules", tmp_path, lambda s: s, [a1])
    once = ex.store.totals("jules")["area_m2"]
    ex.process("jules", tmp_path, lambda s: s, [a1, a2])
    assert once > 0 and ex.store.totals("jules")["area_m2"] == once
    assert ex.store.totals("marie")["area_m2"] == 0


def test_polygon_area_and_holes():
    import numpy as np

    k = 111_320 * math.cos(math.radians(45))
    sq = lambda lon, lat, m: [[lon, lat], [lon + m / k, lat], [lon + m / k, lat + m / 111_320], [lon, lat + m / 111_320]]
    poly = [[sq(4.0, 45.0, 1000), sq(4.0 + 400 / k, 45.0 + 400 / 111_320, 200)]]
    assert polygons_area(poly) == pytest.approx(1000**2 - 200**2, rel=0.01)
    lats = np.array([45.0 + 100 / 111_320, 45.0 + 500 / 111_320, 45.0 + 2000 / 111_320])
    lons = np.array([4.0 + 100 / k, 4.0 + 500 / k, 4.0 + 100 / k])
    assert in_polygons(lats, lons, poly).tolist() == [True, False, False]  # inside, in the hole, outside


@pytest.mark.parametrize("block", [1, 2, 8])
def test_veil_is_cleared_over_the_area_discovered(block):
    import numpy as np

    cells = corridor_cells([track([(5, 0), (5, 3), (7, 3)])])  # a corner, to have staircases and a bend
    cells -= {c for c in cells if c[0] % 7 == 0 and c[1] % 5 == 0}  # undiscovered specks inside
    polygons = veil(cells, block)["geometry"]["coordinates"]
    lat, lon = node(5, 2)
    on, beside, far = (lat, lon), (lat + 35 / 111_320, lon), (lat + 300 / 111_320, lon)
    veiled = in_polygons(np.array([on[0], beside[0], far[0]]), np.array([on[1], beside[1], far[1]]), polygons)
    assert veiled.tolist() == [False, False, True]
    assert in_polygons(np.array([node(6, 3)[0]]), np.array([node(6, 3)[1]]), polygons).tolist() == [False]  # after the bend


# --- credits ---


def test_credits_history_is_a_capped_welcome_then_new_runs_earn_in_full(tmp_path, g, monkeypatch):
    from app.explore import credits

    pois = PoiStore(tmp_path / "pois.sqlite")
    lat, lon = node(8, 2)
    pois.add([Poi("n9", lat + 10 / 111_320, lon, "nature", "peak", "Crêt", 40, 12)])
    ex = explorer(tmp_path, g, pois)
    monkeypatch.setattr(credits, "WELCOME_CAP", 3)
    ex.process("jules", tmp_path, lambda s: s, [Activity("strava:20", "run", "r", T0, track([(2, 0), (2, 10)]))])
    s = credits.summary(ex.store, "jules")
    # the history: 1.6 km run, all new, 0.17 km² -> 1.6 + 3.2 + 1.7 = 6 once rounded (capped at 3); quiet
    assert s["history"] == 6 and s["welcome"] == 3 and s["balance"] == 3 and s["entries"] == [] and s["new"] == 0

    later = datetime.now(timezone.utc)
    ex.process("jules", tmp_path, lambda s: s, [Activity("strava:21", "run", "r", later, track([(8, 0), (8, 5)], start=later))], announce=True)
    s = credits.summary(ex.store, "jules")
    by_key = {e["key"]: e for e in s["entries"]}
    run = by_key["act:strava:21"]
    assert run["detail"]["run_m"] == pytest.approx(600, rel=0.05) and run["detail"]["new_m"] == pytest.approx(600, rel=0.02)
    assert run["amount"] == credits.activity_credits(run["detail"]["run_m"], run["detail"]["new_m"], run["detail"]["area_m2"])
    assert by_key["poi:n9"]["amount"] == 10  # a summit
    assert by_key["ach:badge:peaks:1"]["amount"] == credits.BADGE_CREDITS
    assert s["balance"] == 3 + sum(e["amount"] for e in s["entries"]) and s["new"] == s["balance"] - 3

    # never twice: the same activity again, a re-processing
    assert credits.sync(ex.store, "jules", ex._achievements("jules")) == 0
    ex.store.mark_credits_seen("jules")
    assert credits.summary(ex.store, "jules")["new"] == 0


def test_credits_of_an_old_activity_imported_late_go_to_the_welcome(tmp_path, g):
    from app.explore import credits

    ex = explorer(tmp_path, g)
    ex.process("jules", tmp_path, lambda s: s, [])  # the credits begin (empty account)
    old, recent = datetime.now(timezone.utc) - timedelta(days=60), datetime.now(timezone.utc) - timedelta(days=3)
    ex.process("jules", tmp_path, lambda s: s, [Activity("strava:30", "run", "r", old, track([(2, 0), (2, 10)], start=old)),
                                               Activity("strava:31", "run", "r", recent, track([(6, 0), (6, 10)], start=recent))], announce=True)
    rows = {r["key"]: r["history"] for r in ex.store.credits("jules")}
    assert rows["act:strava:30"] is True and rows["act:strava:31"] is False


def test_credits_backfill_the_km_of_activities_processed_before_them(tmp_path, g):
    from app.explore import credits

    ex = explorer(tmp_path, g)
    act = Activity("strava:40", "run", "r", T0, track([(2, 0), (2, 10)]))
    ex.process("jules", tmp_path, lambda s: s, [act])
    with ex.store._db:  # as recorded before the credits
        ex.store._db.execute("UPDATE processed SET run_m = NULL, area_m2 = NULL, date = NULL")
        ex.store._db.execute("DELETE FROM credits")
        ex.store._db.execute("DELETE FROM credits_meta")
    ex.process("jules", tmp_path, lambda s: s, [act])
    rows = {r["key"]: r for r in ex.store.credits("jules")}
    assert rows["act:strava:40"]["detail"]["run_m"] == pytest.approx(1600, rel=0.05)
    assert rows["history:area"]["detail"]["area_m2"] == ex.store.totals("jules")["area_m2"]
    assert credits.summary(ex.store, "jules")["history"] == 5 + 2  # the run (4.8), its area apart (1.7)


def test_credits_api_is_per_user(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app import api
    from app.explore import credits
    from test_pipeline import make_data

    monkeypatch.setattr(api, "DATA_DIR", make_data(tmp_path))
    store = api.explorer().store
    store.add_activity("tester", "strava:1", [], [{"poi": "n1", "name": "Pic", "category": "nature", "kind": "peak", "first_date": "2026-10-01"}])
    credits.sync(store, "tester", [])  # history
    store.add_activity("tester", "strava:2", [], [{"poi": "n2", "name": "Saut", "category": "water", "kind": "waterfall",
                                                     "first_date": datetime.now(timezone.utc).isoformat()}])
    credits.sync(store, "tester", [])
    with TestClient(api.app) as c:
        s = c.get("/api/credits").json()
        assert s["welcome"] == 10 and s["balance"] == 20 and s["new"] == 10 and [e["label"] for e in s["entries"]] == ["Saut"]
        assert c.post("/api/explore/seen", json={"ids": ["credits"]}).json() == {"ok": True}
        assert c.get("/api/credits").json()["new"] == 0
    assert credits.summary(store, "marie")["balance"] == 0


def test_credits_monthly_cap(tmp_path, g, monkeypatch):
    from app.explore import credits

    ex = explorer(tmp_path, g)
    ex.process("jules", tmp_path, lambda s: s, [])  # the credits begin
    monkeypatch.setattr(credits, "MONTHLY_CAP", 5)
    now = datetime.now(timezone.utc)
    acts = [Activity(f"strava:5{i}", "run", "r", now - timedelta(hours=i), track([(i * 2, 0), (i * 2, 10)], start=now - timedelta(hours=i)))
            for i in range(3)]
    ex.process("jules", tmp_path, lambda s: s, acts, announce=True)
    rows = [r for r in ex.store.credits("jules") if r["kind"] == "activity"]
    assert len(rows) == 3 and sum(r["amount"] for r in rows) == 5  # all recorded, paid up to the cap
    assert any(r["amount"] == 0 and r["detail"]["capped_from"] > 0 for r in rows)  # never paid later
    s = credits.summary(ex.store, "jules")
    assert s["month"] == {"earned": 5, "cap": 5} and s["balance"] == 5


def test_a_route_costs_a_credit_per_km(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app import api
    from app.explore import credits
    from test_pipeline import make_data

    monkeypatch.setattr(api, "DATA_DIR", make_data(tmp_path))
    monkeypatch.setattr(api, "ROUTE_CREDITS", True)
    store = api.explorer().store
    fake = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": 0, "geometry": {"type": "LineString", "coordinates": [[4.8, 45.7], [4.81, 45.71]]}, "properties": {"distance_m": 2400}}
    ]}
    with TestClient(api.app) as c:
        c.get("/api/activities")
        monkeypatch.setattr(api._workspaces["tester"].routing, "generate", lambda *x, **k: fake)
        monkeypatch.setattr(api, "places_along", lambda coords: [])
        r = c.post("/api/routes", json={"start": [4.8, 45.7], "distance_km": 2})
        assert r.status_code == 402 and "crédits insuffisants" in r.json()["detail"]
        credits.sync(store, "tester", [])  # the credits begin
        store.add_activity("tester", "strava:9", [], [{"poi": "n1", "name": "Pic", "category": "nature", "kind": "peak",
                                                        "first_date": datetime.now(timezone.utc).isoformat()}])
        credits.sync(store, "tester", [])
        assert credits.balance(store, "tester") == 10
        out = c.post("/api/routes", json={"start": [4.8, 45.7], "distance_km": 2}).json()
        assert out["credits"] == {"spent": 2, "balance": 8}  # 2.4 km
        s = c.get("/api/credits").json()
        assert s["entries"][0]["kind"] == "spend" and s["entries"][0]["amount"] == -2 and s["balance"] == 8
        assert s["new"] == 10  # the spending is not a gain to announce
