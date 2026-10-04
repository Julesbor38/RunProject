"""Route generation on the walkable graph, weighted by the user's preferences.

Cost of an edge = length x factor, the factor growing with what the user wants
to avoid (roads, traffic, darkness, already-run or never-run paths).
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

from .elevation import climb
from .graph import EARTH_M_PER_DEG_LAT, Edge, Graph

MIN_FACTOR = 0.5  # lowest possible cost factor, keeps the A* heuristic admissible
REUSE_PENALTY = 4.0  # discourages running the same edge twice in a loop
FLAT_CLIMB_COST = 12.0  # hills=-1: each meter climbed costs as much as 12 m of flat
HILLY_CLIMB_BONUS = 4.0  # hills=+1: each meter climbed saves 4 m (bounded by MIN_FACTOR)
PROFILE_STEP_M = 25.0
EQUILATERAL = math.pi / 3
NARROW = math.radians(25)  # apex angle of the elongated loop shape
WAYPOINT_DZ_WEIGHT = 8.0  # meters of waypoint offset traded per meter of elevation difference


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
        }


def shortest(g: Graph, src: int, dst: int, p: Preferences, penalty: dict[int, float] | None = None) -> Route | None:
    """A* from src to dst with the preference-weighted cost."""
    penalty = penalty or {}
    cw = climb_weight(p)
    gx, gy = g.xy(dst)
    best = {src: 0.0}
    prev: dict[int, tuple[int, int]] = {}  # node -> (edge index, previous node)
    heap = [(0.0, 0.0, src)]
    factors: dict[int, float] = {}
    while heap:
        _, cost, node = heapq.heappop(heap)
        if node == dst:
            break
        if cost > best.get(node, math.inf):
            continue
        for idx in g.adj.get(node, ()):
            e = g.edges[idx]
            f = factors.get(idx)
            if f is None:
                f = factors[idx] = edge_factor(e, p)
            nxt = g.other(e, node)
            step = e.length_m * f * penalty.get(idx, 1.0)
            if cw:
                step = max(step + cw * e.ascent(e.u != node), MIN_FACTOR * e.length_m)
            c = cost + step
            if c < best.get(nxt, math.inf):
                best[nxt] = c
                prev[nxt] = (idx, node)
                x, y = g.xy(nxt)
                heapq.heappush(heap, (c + MIN_FACTOR * math.hypot(gx - x, gy - y), c, nxt))
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
) -> list[Route]:
    """Loops of about `distance_m` through two waypoints placed in a triangle around the start.

    Each bearing gives one candidate; its size is corrected once from the first
    attempt's length. Best candidates (cost per meter + distance error + distance
    to the wanted ascent range) are returned.
    """
    candidates: list[tuple[float, Route]] = []
    variants = [(p, EQUILATERAL)]
    if ascent_range is not None and g.ele:
        # The climb weight steers the ascent; another setting and a narrow loop shape widen the
        # spread of ascents (a narrow loop can follow a valley, or climb straight up and back).
        other = max(-1.0, min(1.0, p.hills + (0.6 if p.hills <= 0.4 else -0.6)))
        variants += [(Preferences(**{**p.__dict__, "hills": other}), EQUILATERAL), (p, NARROW)]
    for b, (vi, (prefs, apex)) in ((b, v) for v in enumerate(variants) for b in range(n_bearings)):
        bearing = 2 * math.pi * (b + vi / len(variants)) / n_bearings  # variants explore offset bearings
        # Perimeter 2s + 2s.sin(apex/2); roads are ~20 % longer than straight lines.
        side = distance_m / (1.2 * (2 + 2 * math.sin(apex / 2)))
        route = None
        for _ in range(2):
            route = _triangle(g, start, bearing, side, prefs, apex)
            if route is None:
                break
            length = sum(g.edges[i].length_m for i, _ in route.edges)
            if abs(length - distance_m) / distance_m < 0.1:
                break
            side *= distance_m / max(length, 1.0)
        if route is None:
            continue
        length = sum(g.edges[i].length_m for i, _ in route.edges)
        error = abs(length - distance_m) / distance_m
        score = route.cost / length + 3.0 * error + 2.0 * _repeated_length(g, route.edges) / length
        if ascent_range is not None and g.ele:
            score += 4.0 * _range_miss(route.ascent(g)[0], ascent_range)
        candidates.append((score, route))
    candidates.sort(key=lambda c: c[0])
    return _diverse([r for _, r in candidates], g, n_results)


def point_to_point(g: Graph, src: int, dst: int, p: Preferences) -> list[Route]:
    route = shortest(g, src, dst, p)
    return [route] if route else []


def _triangle(g: Graph, start: int, bearing: float, side: float, p: Preferences, apex: float = math.pi / 3) -> Route | None:
    lat, lon = g.coords[start]
    waypoints = []
    radius = side / 3

    z0 = g.ele.get(start)

    def penalty(node: int) -> float:
        # Pull waypoints onto paths the user likes; they shape the whole loop.
        best = min(edge_factor(g.edges[i], p) for i in g.adj[node])
        out = radius * (best - MIN_FACTOR) / 2
        if z0 is not None and p.hills and node in g.ele:
            # Flat: stay near the start's elevation (valleys, contour lines). Hilly: reach for height.
            dz = abs(g.ele[node] - z0)
            out += -p.hills * WAYPOINT_DZ_WEIGHT * dz
        return out

    for angle in (bearing, bearing + apex):
        wlat = lat + side * math.cos(angle) / EARTH_M_PER_DEG_LAT
        wlon = lon + side * math.sin(angle) / g.m_per_deg_lon
        w = g.nearest_node(wlat, wlon, max_m=radius, penalty=penalty)
        if w is None:
            return None
        waypoints.append(w)
    edges: list[tuple[int, bool]] = []
    cost, penalty = 0.0, {}
    for a, b in zip([start, *waypoints], [*waypoints, start]):
        leg = shortest(g, a, b, p, penalty)
        if leg is None:
            return None
        edges += leg.edges
        cost += leg.cost
        penalty.update((idx, REUSE_PENALTY) for idx, _ in leg.edges)
    return Route(edges, cost)


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
