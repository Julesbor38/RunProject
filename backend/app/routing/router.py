"""Route generation on the walkable graph, weighted by the user's preferences.

Cost of an edge = length x factor, the factor growing with what the user wants
to avoid (roads, traffic, darkness, already-run or never-run paths).
"""
from __future__ import annotations

import heapq
import itertools
import math
from dataclasses import dataclass

from .elevation import climb
from .graph import EARTH_M_PER_DEG_LAT, Edge, Graph
from .job import Job

MIN_FACTOR = 0.5  # lowest possible cost factor, keeps the A* heuristic admissible
REUSE_PENALTY = 4.0  # discourages running the same edge twice in a loop
FLAT_CLIMB_COST = 12.0  # hills=-1: each meter climbed costs as much as 12 m of flat
HILLY_CLIMB_BONUS = 4.0  # hills=+1: each meter climbed saves 4 m (bounded by MIN_FACTOR)
PROFILE_STEP_M = 25.0
EQUILATERAL = math.pi / 3
NARROW = math.radians(25)  # apex angle of the elongated loop shape
WAYPOINT_DZ_WEIGHT = 8.0  # meters of waypoint offset traded per meter of elevation difference
FLATTEST_CLIMB_COST = 40.0  # "le plus plat": each meter climbed costs as much as 40 m of flat
PETAL_M = 3500.0  # preferred length of each small loop when a flat route is made of several


@dataclass
class Preferences:
    nature: float = 0.5  # 0..1: prefer dirt trails over pavement
    avoid_traffic: float = 0.7  # 0..1
    lit: float = 0.0  # 0..1: prefer lit streets (night runs)
    familiarity: float = 0.0  # -1 discovery .. +1 paths already run
    avoid_steps: float = 0.3  # 0..1
    hills: float = 0.0  # -1 as flat as possible .. +1 seek climbs


def climb_weight(p: Preferences) -> float:
    """Extra cost per meter of ascent (negative: climbing is rewarded)."""
    return -p.hills * FLAT_CLIMB_COST if p.hills < 0 else -p.hills * HILLY_CLIMB_BONUS


def edge_factor(e: Edge, p: Preferences) -> float:
    f = 1.0
    f += 3.0 * p.nature * (1 - e.nature)
    f += 1.5 * p.avoid_traffic * e.traffic
    f += 3.0 * p.lit * (1 - e.lit)
    f += 2.0 * p.avoid_steps * e.steps
    if p.familiarity > 0:
        f *= 1 - 0.5 * p.familiarity * e.familiar
    elif p.familiarity < 0:
        f *= 1 + 1.5 * -p.familiarity * e.familiar
    return max(f, MIN_FACTOR)


@dataclass
class Route:
    edges: list[tuple[int, bool]]  # (edge index, reversed)
    cost: float
    petals: int = 1  # number of loops from the start it is made of

    def length(self, g: Graph) -> float:
        return sum(g.edges[i].length_m for i, _ in self.edges)

    def coords(self, g: Graph) -> list[list[float]]:
        out: list[list[float]] = []
        for idx, rev in self.edges:
            nodes = g.edges[idx].nodes[::-1] if rev else g.edges[idx].nodes
            pts = [[round(g.coords[n][1], 6), round(g.coords[n][0], 6)] for n in nodes]
            out.extend(pts if not out else pts[1:])
        return out

    def coords3d(self, g: Graph) -> list[list[float]]:
        """[lon, lat, ele] when elevation is known."""
        out: list[list[float]] = []
        for idx, rev in self.edges:
            nodes = g.edges[idx].nodes[::-1] if rev else g.edges[idx].nodes
            pts = [[round(g.coords[n][1], 6), round(g.coords[n][0], 6)] + ([g.ele[n]] if n in g.ele else []) for n in nodes]
            out.extend(pts if not out else pts[1:])
        return out

    def profile(self, g: Graph) -> list[list[float]]:
        """[[distance_m, elevation_m], ...] resampled every PROFILE_STEP_M (empty without DEM)."""
        if not g.ele:
            return []
        pts = self.coords3d(g)
        k = g.m_per_deg_lon
        out, dist, next_at = [], 0.0, 0.0
        for a, b in zip(pts, pts[1:]):
            seg = math.hypot((b[0] - a[0]) * k, (b[1] - a[1]) * EARTH_M_PER_DEG_LAT)
            while seg and next_at <= dist + seg:
                t = (next_at - dist) / seg
                out.append([round(next_at), round(a[2] + t * (b[2] - a[2]), 1)])
                next_at += PROFILE_STEP_M
            dist += seg
        if pts and len(pts[-1]) > 2:
            out.append([round(dist), pts[-1][2]])
        return out

    def ascent(self, g: Graph) -> tuple[float, float]:
        return climb([z for _, z in self.profile(g)])

    def stats(self, g: Graph) -> dict:
        total = sum(g.edges[i].length_m for i, _ in self.edges) or 1.0
        profile = self.profile(g)
        up, down = climb([z for _, z in profile])

        def share(pred) -> float:
            return round(sum(g.edges[i].length_m for i, _ in self.edges if pred(g.edges[i])) / total, 3)

        return {
            "distance_m": round(total),
            "nature": share(lambda e: e.nature >= 0.5),
            "lit": round(sum(g.edges[i].length_m * g.edges[i].lit for i, _ in self.edges) / total, 3),
            "busy_roads": share(lambda e: e.traffic >= 2),
            "familiar": round(sum(g.edges[i].length_m * g.edges[i].familiar for i, _ in self.edges) / total, 3),
            "repeated": round(_repeated_length(g, self.edges) / total, 3),
            "ascent_m": round(up),
            "descent_m": round(down),
            "ele_min": min((z for _, z in profile), default=None),
            "ele_max": max((z for _, z in profile), default=None),
            "profile": profile,
            "petals": self.petals,
        }


class Weights:
    """Preference-weighted cost of every edge in both directions, computed once per request.

    `adj[node]` lists (next node, edge index, step cost); `floor` is the lowest cost per
    meter in the graph, which keeps the A* heuristic admissible and as tight as possible.
    """

    def __init__(self, g: Graph, p: Preferences, climb_cost: float | None = None):
        cw = climb_weight(p) if climb_cost is None else climb_cost
        self.factor = [edge_factor(e, p) for e in g.edges]
        self.adj: dict[int, list[tuple[int, int, float]]] = {n: [] for n in g.adj}
        floor = math.inf
        for idx, (e, f) in enumerate(zip(g.edges, self.factor)):
            for a, b, rev in ((e.u, e.v, False), (e.v, e.u, True)):
                step = e.length_m * f
                if cw:
                    step = max(step + cw * e.ascent(rev), MIN_FACTOR * e.length_m)
                self.adj[a].append((b, idx, step))
                if e.length_m > 0:
                    floor = min(floor, step / e.length_m)
        self.floor = floor if floor < math.inf else MIN_FACTOR


def shortest(
    g: Graph, src: int, dst: int, p: Preferences, penalty: dict[int, float] | None = None, w: Weights | None = None
) -> Route | None:
    """A* from src to dst with the preference-weighted cost."""
    penalty = penalty or {}
    w = w or Weights(g, p)
    adj, h = w.adj, w.floor
    k, ky = g.m_per_deg_lon, EARTH_M_PER_DEG_LAT
    coords = g.coords
    glat, glon = coords[dst]
    gx, gy = glon * k, glat * ky
    best = {src: 0.0}
    prev: dict[int, tuple[int, int]] = {}  # node -> (edge index, previous node)
    heap = [(0.0, 0.0, src)]
    while heap:
        _, cost, node = heapq.heappop(heap)
        if node == dst:
            break
        if cost > best[node]:
            continue
        for nxt, idx, step in adj[node]:
            c = cost + (step * penalty[idx] if idx in penalty else step)
            if c < best.get(nxt, math.inf):
                best[nxt] = c
                prev[nxt] = (idx, node)
                lat, lon = coords[nxt]
                heapq.heappush(heap, (c + h * math.hypot(gx - lon * k, gy - lat * ky), c, nxt))
    if dst not in best:
        return None
    edges, node = [], dst
    while node != src:
        idx, before = prev[node]
        edges.append((idx, g.edges[idx].u != before))
        node = before
    return Route(edges[::-1], best[dst])


def loop(
    g: Graph,
    start: int,
    distance_m: float,
    p: Preferences,
    n_results: int = 3,
    n_bearings: int = 8,
    ascent_range: tuple[float, float] | None = None,
    job: Job | None = None,
) -> list[Route]:
    """Loops of about `distance_m` through two waypoints placed in a triangle around the start.

    Each bearing gives one candidate; its size is corrected once from the first
    attempt's length. Best candidates (cost per meter + distance error + distance
    to the wanted ascent range) are returned.
    """
    variants = [(p, EQUILATERAL)]
    if ascent_range is not None and g.ele:
        # The climb weight steers the ascent; another setting and a narrow loop shape widen the
        # spread of ascents (a narrow loop can follow a valley, or climb straight up and back).
        variants += [(_other_hills(p), EQUILATERAL), (p, NARROW)]
    job = job or Job()
    job.step("routes", 0, len(variants) * n_bearings)
    shapes = [(prefs, apex, Weights(g, prefs)) for prefs, apex in variants]
    routes = _triangle_loops(g, start, distance_m, shapes, n_bearings, job)
    routes.sort(key=lambda r: _score(g, r, distance_m, ascent_range))
    return _diverse(routes, g, n_results)


def flattest(
    g: Graph,
    start: int,
    distance_m: float,
    p: Preferences,
    n_results: int = 3,
    n_bearings: int = 12,
    job: Job | None = None,
) -> list[Route]:
    """The flattest routes of about `distance_m` from `start`: one big loop, or several small
    loops ("petals") from the start that stay on the flattest ground around it.

    A big loop often has to climb out of a valley or off a plateau; 2-4 loops of 2-5 km can
    keep to a valley floor or a balcony path. Routes are ranked by ascent per km.
    """
    job = job or Job()
    flat = Preferences(**{**p.__dict__, "hills": -1.0})
    w = Weights(g, flat, climb_cost=FLATTEST_CLIMB_COST)
    # Out and back (apex None) too: in a steep valley, the only flat ground may be one balcony path.
    shapes = [(flat, EQUILATERAL, w), (flat, NARROW, w), (flat, None, w)]
    # One loop, and the two petal counts closest to PETAL_M each (petals of 2-5 km).
    counts = sorted((k for k in range(2, 9) if 2000 <= distance_m / k <= 5000), key=lambda k: abs(distance_m / k - PETAL_M))[:2]
    counts = [1, *sorted(counts)]
    job.step("routes", 0, len(counts) * len(shapes) * n_bearings)
    candidates: list[Route] = []
    for k in counts:
        loops = _triangle_loops(g, start, distance_m / k, shapes, n_bearings, job)
        if k == 1:
            candidates += loops
        else:
            candidates += _petal_routes(g, loops, k, distance_m / k)
    candidates.sort(key=lambda r: _flat_score(g, r, distance_m))
    return _diverse(candidates, g, n_results)


def _petal_routes(g: Graph, loops: list[Route], k: int, petal_m: float, n_petals: int = 5) -> list[Route]:
    """Routes made of `k` of the flattest small loops (a loop may be run twice when few are flat)."""
    best = _diverse(sorted(loops, key=lambda r: _flat_score(g, r, petal_m)), g, n_petals, max_overlap=0.5)
    asc = [r.ascent(g)[0] for r in best]
    length = [r.length(g) for r in best]
    # The same loop at most twice: only worth it when the other loops are much hillier.
    combos = [c for c in itertools.combinations_with_replacement(range(len(best)), k) if max(map(c.count, c)) <= 2]
    # Ascent adds up across loops from the same start: cheap pre-ranking, exact ranking afterwards.
    combos.sort(key=lambda c: sum(asc[i] for i in c) / max(sum(length[i] for i in c), 1.0))
    return [Route([e for i in c for e in best[i].edges], sum(best[i].cost for i in c), petals=k) for c in combos[:12]]


def _flat_score(g: Graph, route: Route, distance_m: float) -> float:
    """Lower is better, in meters of ascent per km: ascent first, then distance error, repeats and preferences."""
    length = max(route.length(g), 1.0)
    per_km = route.ascent(g)[0] / (length / 1000)
    return per_km + 40.0 * abs(length - distance_m) / distance_m + 8.0 * _repeated_length(g, route.edges) / length + route.cost / length / 10


def _triangle_loops(
    g: Graph,
    start: int,
    distance_m: float,
    shapes: list[tuple[Preferences, float | None, Weights]],
    n_bearings: int,
    job: Job,
) -> list[Route]:
    """One loop of about `distance_m` per bearing and shape (preferences, apex angle, weights):
    a triangle through two waypoints, or with apex None a single waypoint and back (by another
    way when there is one), its size corrected once from the first attempt's length."""
    lat, lon = g.coords[start]
    out = []
    for b, (vi, (prefs, apex, w)) in ((b, v) for v in enumerate(shapes) for b in range(n_bearings)):
        job.advance()
        bearing = 2 * math.pi * (b + vi / len(shapes)) / n_bearings  # shapes explore offset bearings

        def triangle(side: float, bearing=bearing, prefs=prefs, apex=apex, w=w) -> Route | None:
            angles = (bearing,) if apex is None else (bearing, bearing + apex)
            corners = [_offset(g, lat, lon, side, angle) for angle in angles]
            return _route_via(g, start, start, corners, side / (2 if apex is None else 3), prefs, w)

        # Perimeter 2s + 2s.sin(apex/2) (2s out and back); roads are ~20 % longer than straight lines.
        perimeter = 2 if apex is None else 2 + 2 * math.sin(apex / 2)
        route = _sized(g, triangle, distance_m / (1.2 * perimeter), distance_m)
        if route is not None:
            out.append(route)
    return out


def point_to_point(
    g: Graph,
    src: int,
    dst: int,
    p: Preferences,
    distance_m: float | None = None,
    ascent_range: tuple[float, float] | None = None,
    n_results: int = 3,
    n_angles: int = 8,
    job: Job | None = None,
    flat: bool = False,
) -> list[Route]:
    """The best route from src to dst or, given `distance_m`, routes of about that length.
    `flat`: the flattest ones (climbs weigh much more, ranked by ascent per km).

    Longer routes go through one waypoint on an ellipse whose foci are src and dst:
    any point of it makes a src-waypoint-dst path of the same straight-line length.
    A target shorter than the direct route yields the direct route alone.
    """
    job = job or Job()
    job.step("routes")
    if flat:
        p, ascent_range = Preferences(**{**p.__dict__, "hills": -1.0}), None
    weights = Weights(g, p, climb_cost=FLATTEST_CLIMB_COST if flat else None)
    direct = shortest(g, src, dst, p, w=weights)
    if direct is None or not distance_m or direct.length(g) >= distance_m * 0.95:
        return [direct] if direct else []
    (lat1, lon1), (lat2, lon2) = g.coords[src], g.coords[dst]
    k = g.m_per_deg_lon
    dx, dy = (lon2 - lon1) * k, (lat2 - lat1) * EARTH_M_PER_DEG_LAT
    c = math.hypot(dx, dy) / 2  # half the focal distance
    axis = math.atan2(dx, dy)  # bearing from src to dst
    mid_lat, mid_lon = (lat1 + lat2) / 2, (lon1 + lon2) / 2
    score = (lambda r: _flat_score(g, r, distance_m)) if flat else (lambda r: _score(g, r, distance_m, ascent_range))
    candidates = [(score(direct), direct)]
    variants = [p] + ([_other_hills(p)] if ascent_range is not None and g.ele else [])
    all_weights = [weights] + [Weights(g, v) for v in variants[1:]]
    job.step("routes", 0, len(variants) * n_angles)
    for a, (vi, prefs) in ((a, v) for v in enumerate(variants) for a in range(n_angles)):
        job.advance()
        # Odd multiples of pi/n: never on the src-dst axis, which would mean running past dst and back.
        theta = math.pi * (2 * a + 1 + vi) / n_angles

        def via(total: float) -> Route | None:
            semi_major = max(total / 2, c * 1.05)
            semi_minor = math.sqrt(semi_major**2 - c**2)
            along, across = semi_major * math.cos(theta), semi_minor * math.sin(theta)
            dist = math.hypot(along, across)
            point = _offset(g, mid_lat, mid_lon, dist, axis + math.atan2(across, along))
            return _route_via(g, src, dst, [point], max(semi_minor, 300.0) / 2, prefs, all_weights[vi])

        route = _sized(g, via, distance_m / 1.2, distance_m)  # roads are ~20 % longer than straight lines
        if route is not None:
            candidates.append((score(route), route))
    candidates.sort(key=lambda c: c[0])
    return _diverse([r for _, r in candidates], g, n_results)


def _other_hills(p: Preferences) -> Preferences:
    """Another climb setting, to widen the spread of ascents among candidates."""
    other = max(-1.0, min(1.0, p.hills + (0.6 if p.hills <= 0.4 else -0.6)))
    return Preferences(**{**p.__dict__, "hills": other})


def _offset(g: Graph, lat: float, lon: float, dist: float, bearing: float) -> tuple[float, float]:
    return lat + dist * math.cos(bearing) / EARTH_M_PER_DEG_LAT, lon + dist * math.sin(bearing) / g.m_per_deg_lon


def _sized(g: Graph, build, size: float, distance_m: float) -> Route | None:
    """`build(size)`, with the size corrected once from the first attempt's length."""
    route = build(size)
    if route is not None and abs(route.length(g) - distance_m) / distance_m >= 0.1:
        route = build(size * distance_m / max(route.length(g), 1.0)) or route
    return route


def _score(g: Graph, route: Route, distance_m: float, ascent_range: tuple[float, float] | None) -> float:
    """Lower is better: cost per meter + distance error + repeated parts + miss of the D+ range."""
    length = max(route.length(g), 1.0)
    score = route.cost / length + 3.0 * abs(length - distance_m) / distance_m + 2.0 * _repeated_length(g, route.edges) / length
    if ascent_range is not None and g.ele:
        score += 4.0 * _range_miss(route.ascent(g)[0], ascent_range)
    return score


def _route_via(
    g: Graph,
    src: int,
    dst: int,
    points: list[tuple[float, float]],
    radius: float,
    p: Preferences,
    weights: Weights,
) -> Route | None:
    """src -> junctions near each (lat, lon) point -> dst, discouraging reuse of earlier legs."""
    z0 = g.ele.get(src)

    def penalty(node: int) -> float:
        # Pull waypoints onto paths the user likes; they shape the whole route.
        best = min(weights.factor[i] for i in g.adj[node])
        out = radius * (best - MIN_FACTOR) / 2
        if z0 is not None and p.hills and node in g.ele:
            # Flat: stay near the start's elevation (valleys, contour lines). Hilly: reach for height.
            dz = abs(g.ele[node] - z0)
            out += -p.hills * WAYPOINT_DZ_WEIGHT * dz
        return out

    waypoints = []
    for lat, lon in points:
        w = g.nearest_node(lat, lon, max_m=radius, penalty=penalty)
        if w is None:
            return None
        waypoints.append(w)
    return _through(g, [src, *waypoints, dst], p, weights)


def _through(g: Graph, nodes: list[int], p: Preferences, weights: Weights) -> Route | None:
    """The best legs between consecutive nodes, discouraging reuse of earlier legs."""
    edges: list[tuple[int, bool]] = []
    cost, reuse = 0.0, {}
    for a, b in zip(nodes, nodes[1:]):
        if a == b:
            continue
        leg = shortest(g, a, b, p, reuse, weights)
        if leg is None:
            return None
        edges += leg.edges
        cost += leg.cost
        reuse.update((idx, REUSE_PENALTY) for idx, _ in leg.edges)
    return Route(edges, cost)


def _bearing(g: Graph, a: int, b: int) -> float:
    (lat1, lon1), (lat2, lon2) = g.coords[a], g.coords[b]
    return math.atan2((lon2 - lon1) * g.m_per_deg_lon, (lat2 - lat1) * EARTH_M_PER_DEG_LAT)


def loop_via(
    g: Graph,
    start: int,
    vias: list[int],
    distance_m: float,
    p: Preferences,
    ascent_range: tuple[float, float] | None = None,
    n_results: int = 3,
    n_bearings: int = 8,
    job: Job | None = None,
) -> list[Route]:
    """Loops through fixed points (« Passer par ici »), visited in the order of their bearing from the start.
    When they leave room for it, a free point at each bearing lengthens the loop towards `distance_m`."""
    job = job or Job()
    job.step("routes", 0, n_bearings + 1)
    weights = Weights(g, p)
    lat0, lon0 = g.coords[start]
    by_bearing = lambda nodes: sorted(nodes, key=lambda n: _bearing(g, start, n))  # noqa: E731
    candidates = []
    base = _through(g, [start, *by_bearing(vias), start], p, weights)
    job.advance()
    if base is not None:
        candidates.append(base)
    if base is None or base.length(g) < 0.9 * distance_m:
        for b in range(n_bearings):
            job.advance()

            def with_free_point(side: float, bearing=2 * math.pi * b / n_bearings) -> Route | None:
                lat, lon = _offset(g, lat0, lon0, side, bearing)
                free = g.nearest_node(lat, lon, max_m=max(side / 3, 300.0))
                if free is None:
                    return None
                return _through(g, [start, *by_bearing([*vias, free]), start], p, weights)

            # Perimeter of a triangle start / via / free point ~ 3.6 x its side once roads are followed.
            route = _sized(g, with_free_point, distance_m / 3.6, distance_m)
            if route is not None:
                candidates.append(route)
    candidates.sort(key=lambda r: _score(g, r, distance_m, ascent_range))
    return _diverse(candidates, g, n_results)


def via_route(
    g: Graph,
    src: int,
    dst: int,
    vias: list[int],
    p: Preferences,
    distance_m: float | None = None,
    ascent_range: tuple[float, float] | None = None,
    job: Job | None = None,
) -> list[Route]:
    """src -> fixed points (ordered along src -> dst) -> dst. With `distance_m`, the detour that lengthens
    the route is taken between the last point and dst."""
    weights = Weights(g, p)
    (lat1, lon1), (lat2, lon2) = g.coords[src], g.coords[dst]
    ax, ay = (lon2 - lon1) * g.m_per_deg_lon, (lat2 - lat1) * EARTH_M_PER_DEG_LAT

    def along(n: int) -> float:
        lat, lon = g.coords[n]
        return (lon - lon1) * g.m_per_deg_lon * ax + (lat - lat1) * EARTH_M_PER_DEG_LAT * ay

    order = sorted(vias, key=along)
    head = _through(g, [src, *order], p, weights)
    if head is None:
        return []
    left = distance_m - head.length(g) if distance_m else None
    tails = point_to_point(g, order[-1], dst, p, left if left and left > 0 else None, ascent_range, job=job)
    return [Route(head.edges + t.edges, head.cost + t.cost) for t in tails]


def _range_miss(value: float, rng: tuple[float, float]) -> float:
    """0 inside the range, else the relative distance to it."""
    lo, hi = rng
    if lo <= value <= hi:
        return 0.0
    gap = lo - value if value < lo else value - hi
    return gap / max((lo + hi) / 2, 50.0)


def _repeated_length(g: Graph, edges: list[tuple[int, bool]]) -> float:
    seen, rep = set(), 0.0
    for idx, _ in edges:
        if idx in seen:
            rep += g.edges[idx].length_m
        seen.add(idx)
    return rep


def _diverse(routes: list[Route], g: Graph, n: int, max_overlap: float = 0.6) -> list[Route]:
    """Keep the best routes that share less than `max_overlap` of their length with a kept one."""
    kept: list[Route] = []
    for r in routes:
        ids = {i for i, _ in r.edges}
        length = sum(g.edges[i].length_m for i in ids) or 1.0
        if all(sum(g.edges[i].length_m for i in ids & {j for j, _ in k.edges}) / length < max_overlap for k in kept):
            kept.append(r)
        if len(kept) == n:
            break
    return kept
