import pytest

from app.routing.graph import EARTH_M_PER_DEG_LAT, build_graph, mark_familiar
from app.routing.osm import OsmData, tiles_for_bbox
from app.routing.router import Preferences, edge_factor, flattest, loop, loop_via, point_to_point, shortest, via_route

LAT0, LON0 = 45.76, 4.78
STEP = 200 / EARTH_M_PER_DEG_LAT  # 200 m between grid lines


def grid(n: int = 11, tags=lambda i, j, vertical: {"highway": "residential"}) -> OsmData:
    """n x n street grid; node id = i * 100 + j."""
    nodes = {i * 100 + j: (LAT0 + i * STEP, LON0 + j * STEP * 1.43) for i in range(n) for j in range(n)}
    ways = []
    for i in range(n):
        for j in range(n - 1):
            ways.append(([i * 100 + j, i * 100 + j + 1], tags(i, j, False)))
            ways.append(([j * 100 + i, (j + 1) * 100 + i], tags(j, i, True)))
    return OsmData(nodes, ways)


def detour() -> OsmData:
    """A main road straight from 1 to 3, and a longer dirt trail via 2."""
    nodes = {1: (LAT0, LON0), 2: (LAT0 + 2 * STEP, LON0 + 2 * STEP), 3: (LAT0, LON0 + 4 * STEP)}
    ways = [
        ([1, 3], {"highway": "secondary"}),
        ([1, 2, 3], {"highway": "path"}),
    ]
    return OsmData(nodes, ways)


def test_edges_split_at_junctions_only():
    osm = OsmData(
        {1: (LAT0, LON0), 2: (LAT0, LON0 + STEP), 3: (LAT0, LON0 + 2 * STEP), 4: (LAT0 + STEP, LON0 + STEP)},
        [([1, 2, 3], {"highway": "footway"}), ([2, 4], {"highway": "footway"})],
    )
    g = build_graph(osm)
    assert sorted((e.u, e.v) for e in g.edges) == [(1, 2), (2, 3), (2, 4)]


def test_private_and_foot_no_ways_are_skipped():
    osm = OsmData(
        {1: (LAT0, LON0), 2: (LAT0, LON0 + STEP)},
        [([1, 2], {"highway": "service", "access": "private"}), ([1, 2], {"highway": "track", "foot": "no"})],
    )
    assert build_graph(osm).edges == []


def test_attributes_from_tags():
    osm = OsmData(
        {1: (LAT0, LON0), 2: (LAT0, LON0 + STEP), 3: (LAT0, LON0 + 2 * STEP)},
        [([1, 2], {"highway": "path"}), ([2, 3], {"highway": "primary", "lit": "yes"})],
    )
    path, road = build_graph(osm).edges
    assert path.nature > 0.5 and path.traffic == 0 and path.lit < 0.5
    assert road.nature == 0 and road.traffic == 3 and road.lit == 1


def test_nature_preference_takes_the_trail():
    g = build_graph(detour())
    road = shortest(g, 1, 3, Preferences(nature=0, avoid_traffic=0))
    trail = shortest(g, 1, 3, Preferences(nature=1, avoid_traffic=1))
    assert [g.edges[i].way_tags["highway"] for i, _ in road.edges] == ["secondary"]
    assert {g.edges[i].way_tags["highway"] for i, _ in trail.edges} == {"path"}


def test_familiarity_prefers_or_avoids_run_paths():
    g = build_graph(detour())
    trail = [[LON0, LAT0], [LON0 + 2 * STEP, LAT0 + 2 * STEP], [LON0 + 4 * STEP, LAT0]]
    mark_familiar(g, [trail])
    path_edges = [e for e in g.edges if e.way_tags["highway"] == "path"]
    assert all(e.familiar > 0.9 for e in path_edges)
    road = next(e for e in g.edges if e.way_tags["highway"] == "secondary")
    assert road.familiar < 0.2
    known = Preferences(nature=0, avoid_traffic=0, familiarity=1)
    new = Preferences(nature=0, avoid_traffic=0, familiarity=-1)
    assert edge_factor(path_edges[0], known) < edge_factor(road, known)
    assert edge_factor(path_edges[0], new) > edge_factor(road, new)


def test_loop_returns_to_start_near_target_distance():
    g = build_graph(grid())
    start = 505  # grid center
    routes = loop(g, start, 4000, Preferences())
    assert routes
    for r in routes:
        coords = r.coords(g)
        assert coords[0] == coords[-1]
        assert r.stats(g)["distance_m"] == pytest.approx(4000, rel=0.25)


def test_loop_routes_are_distinct():
    g = build_graph(grid())
    routes = loop(g, 505, 4000, Preferences())
    assert len(routes) >= 2
    a, b = ({i for i, _ in r.edges} for r in routes[:2])
    assert a != b


def test_one_way_without_distance_is_the_best_route():
    g = build_graph(grid())
    routes = point_to_point(g, 303, 707, Preferences())
    assert len(routes) == 1
    assert routes[0].stats(g)["distance_m"] == pytest.approx(1600, rel=0.01)  # Manhattan distance


def test_one_way_reaches_target_distance_between_both_ends():
    g = build_graph(grid())
    routes = point_to_point(g, 303, 707, Preferences(), distance_m=4000)
    assert len(routes) >= 2
    for r in routes:
        coords = r.coords(g)
        assert coords[0] != coords[-1]
        assert g.edges[r.edges[0][0]].nodes[-1 if r.edges[0][1] else 0] == 303
        assert g.edges[r.edges[-1][0]].nodes[0 if r.edges[-1][1] else -1] == 707
    assert routes[0].stats(g)["distance_m"] == pytest.approx(4000, rel=0.15)


def test_one_way_target_shorter_than_direct_route_gives_direct_route():
    g = build_graph(grid())
    routes = point_to_point(g, 303, 707, Preferences(), distance_m=1000)
    assert len(routes) == 1
    assert routes[0].stats(g)["distance_m"] == pytest.approx(1600, rel=0.01)


def test_tiles_cover_bbox():
    tiles = tiles_for_bbox(45.74, 4.76, 45.81, 4.79)
    assert (914, 95) in tiles and (916, 95) in tiles and len(tiles) == 3


def test_home_tiles_cover_frequent_areas_with_margin():
    from app.routing.service import home_tiles

    often = [[(4.775, 45.765), (4.776, 45.766)]] * 3  # tile (915, 95)
    once = [[(5.5, 45.0)]]
    tiles = home_tiles(often + once)
    assert len(tiles) == 10 and tiles[0] == (915, 95)
    assert tiles[-1] == (900, 110)  # crossed once: last, without margin


class SlopeDem:
    """Fake DEM: elevation grows northwards, 1 m per 10 m."""

    def elevations(self, lats, lons):
        import numpy as np

        return (np.asarray(lats) - LAT0) * EARTH_M_PER_DEG_LAT / 10


class PlainAndHillDem:
    """Flat plain south of the grid center, 1 m per 10 m slope north of it."""

    def elevations(self, lats, lons):
        import numpy as np

        north = (np.asarray(lats) - (LAT0 + 5 * STEP)) * EARTH_M_PER_DEG_LAT
        return np.maximum(north, 0) / 10


class ValleyDem:
    """Flat valley floor along the middle row band (rows 4-6), slopes of 1 m per 10 m on both sides."""

    def elevations(self, lats, lons):
        import numpy as np

        off = np.abs(np.asarray(lats) - (LAT0 + 5 * STEP)) * EARTH_M_PER_DEG_LAT
        return np.maximum(off - STEP * EARTH_M_PER_DEG_LAT, 0) / 10


def test_climb_ignores_small_wiggles():
    from app.routing.elevation import climb

    assert climb([100, 101, 100, 101, 100]) == (0, 0)
    assert climb([100, 110, 105, 120, 100]) == (25, 25)


def test_edge_climb_depends_on_direction():
    from app.routing.graph import add_elevation

    osm = OsmData({1: (LAT0, LON0), 2: (LAT0 + STEP, LON0)}, [([1, 2], {"highway": "path"})])
    g = build_graph(osm)
    add_elevation(g, SlopeDem())
    e = g.edges[0]
    assert e.climb_m == pytest.approx(20, abs=0.5) and e.drop_m == 0
    assert e.ascent(reverse=False) == e.climb_m and e.ascent(reverse=True) == 0


def test_flat_preference_does_not_climb_needlessly():
    from app.routing.graph import add_elevation

    g = build_graph(grid(5))
    add_elevation(g, SlopeDem())
    flat = shortest(g, 0, 4, Preferences(hills=-1))  # east along the bottom row: no climb
    assert sum(g.edges[i].ascent(rev) for i, rev in flat.edges) == pytest.approx(0, abs=0.5)


def test_loop_targets_ascent_range():
    from app.routing.graph import add_elevation

    g = build_graph(grid())
    add_elevation(g, PlainAndHillDem())
    low = loop(g, 505, 4000, Preferences(hills=-0.8), ascent_range=(0, 40))[0].stats(g)
    high = loop(g, 505, 4000, Preferences(hills=1), ascent_range=(80, 400))[0].stats(g)
    assert low["ascent_m"] <= 40 < 80 <= high["ascent_m"]
    assert high["profile"][0][0] == 0 and high["profile"][-1][0] == high["distance_m"]


def test_flattest_stays_on_the_valley_floor():
    from app.routing.graph import add_elevation

    g = build_graph(grid())
    add_elevation(g, ValleyDem())
    ranged = loop(g, 505, 4000, Preferences(hills=-0.8), ascent_range=(0, 40))[0]
    routes = flattest(g, 505, 4000, Preferences())
    best = routes[0]
    assert best.ascent(g)[0] <= 5 < ranged.ascent(g)[0]  # a 4 km triangle must climb out of the 400 m wide valley
    assert 3400 <= best.length(g) <= 4600
    first, last = g.edges[best.edges[0][0]], g.edges[best.edges[-1][0]]
    assert (first.v if best.edges[0][1] else first.u) == 505 and (last.u if best.edges[-1][1] else last.v) == 505
    assert all(a.ascent(g)[0] <= b.ascent(g)[0] + 5 for a, b in zip(routes, routes[1:]))  # flattest first


def test_flattest_one_way_avoids_the_hill():
    from app.routing.graph import add_elevation

    g = build_graph(grid())
    add_elevation(g, PlainAndHillDem())
    # 600 -> 610 along the bottom: a target of 3 km needs a detour, which must stay on the plain
    best = point_to_point(g, 0, 10, Preferences(), distance_m=3000, flat=True)[0]
    assert best.ascent(g)[0] <= 5 and best.length(g) >= 2500


def test_cancelled_job_stops_generation():
    from app.routing.job import Cancelled, Job

    g = build_graph(grid())
    job = Job()
    job.cancel()
    with pytest.raises(Cancelled):
        point_to_point(g, 303, 707, Preferences(), distance_m=4000, job=job)


def test_job_reports_route_candidates():
    from app.routing.job import Job

    g = build_graph(grid())
    job = Job()
    point_to_point(g, 303, 707, Preferences(), distance_m=4000, job=job)
    assert job.progress()["stage"] == "routes"
    assert job.done == job.total == 8


def test_failed_tiles_are_reported_not_raised(tmp_path, monkeypatch):
    from app.routing import osm

    def fake(tile):
        if tile == (1, 1):
            raise osm.OverpassError("busy")
        return {"nodes": {}, "ways": []}

    monkeypatch.setattr(osm, "_download", fake)
    downloaded, failed = osm.download_missing([(1, 1), (1, 2), (2, 2)], tmp_path)
    assert (downloaded, failed) == (2, [(1, 1)])
    assert osm.tile_path((1, 2), tmp_path).exists()


def test_download_stops_when_cancelled(tmp_path, monkeypatch):
    from app.routing import osm
    from app.routing.job import Cancelled, Job

    monkeypatch.setattr(osm, "_download", lambda tile: {"nodes": {}, "ways": []})
    job = Job()
    job.cancel()
    with pytest.raises(Cancelled):
        osm.download_missing([(1, 1)], tmp_path, job)


def test_slow_tiles_count_as_failed_after_deadline(tmp_path, monkeypatch):
    import threading

    from app.routing import osm

    release = threading.Event()

    def slow(tile):
        if tile == (1, 1):
            release.wait(5)
        return {"nodes": {}, "ways": []}

    monkeypatch.setattr(osm, "_download", slow)
    try:
        downloaded, failed = osm.download_missing([(1, 1), (1, 2)], tmp_path, deadline_s=0.3)
    finally:
        release.set()
    assert (downloaded, failed) == (1, [(1, 1)])


def test_far_corner_tiles_are_skipped():
    from app.routing.service import _tile_to_segment_m, _tile_of

    start = (LON0, LAT0)
    assert _tile_to_segment_m(_tile_of(*start), start, start) < 0
    i, j = _tile_of(*start)
    side = _tile_to_segment_m((i + 1, j), start, start)
    corner = _tile_to_segment_m((i + 3, j + 3), start, start)
    assert 0 <= side < corner


def test_routes_avoid_a_failed_far_tile(tmp_path, monkeypatch):
    from app.routing import service
    from app.routing.service import RoutingError, RoutingService, _tile_of

    start, end = (LON0 + 3 * STEP * 1.43, LAT0 + 3 * STEP), (LON0 + 7 * STEP * 1.43, LAT0 + 7 * STEP)
    far = (_tile_of(*start)[0] - 1, _tile_of(*start)[1])  # south neighbour, within reach
    monkeypatch.setattr(service, "load_tiles", lambda tiles, cache_dir: grid())
    svc = RoutingService(tmp_path, [])

    def failing(*bad):
        return lambda tiles, cache_dir, job=None, deadline_s=None, stage="download": (0, [t for t in tiles if t in bad])

    monkeypatch.setattr(service, "download_missing", failing(far))
    fc = svc.generate(start, Preferences(), distance_m=4000, end=end)
    assert fc["features"] and "warning" in fc

    svc = RoutingService(tmp_path, [])
    monkeypatch.setattr(service, "download_missing", failing(_tile_of(*start)))
    with pytest.raises(RoutingError, match="départ"):
        svc.generate(start, Preferences(), distance_m=4000, end=end)


def _nodes_of(g, route):
    return {n for idx, _ in route.edges for n in (g.edges[idx].u, g.edges[idx].v)}


def test_loop_passes_through_the_points_de_passage():
    g = build_graph(grid())
    via = 808  # 600 m north, 600 m east of the start (505)
    routes = loop_via(g, 505, [via], 4000, Preferences())
    assert routes and all(via in _nodes_of(g, r) for r in routes)
    first, last = g.edges[routes[0].edges[0][0]], g.edges[routes[0].edges[-1][0]]
    assert 505 in (first.u, first.v) and 505 in (last.u, last.v)  # back to the start
    assert 3000 <= routes[0].length(g) <= 5200


def test_loop_through_a_far_point_is_longer_than_asked():
    g = build_graph(grid())
    routes = loop_via(g, 505, [1010], 1000, Preferences())  # the corner, ~1.4 km away for a 1 km loop
    assert routes and routes[0].length(g) >= 2000 and 1010 in _nodes_of(g, routes[0])


def test_one_way_through_points_then_to_the_end():
    g = build_graph(grid())
    route = via_route(g, 0, 10, [505], Preferences())[0]  # bottom-left -> bottom-right via the centre
    nodes = _nodes_of(g, route)
    assert {0, 505, 10} <= nodes
    longer = via_route(g, 0, 10, [505], Preferences(), distance_m=4500)[0]
    assert longer.length(g) > route.length(g) and 505 in _nodes_of(g, longer)
