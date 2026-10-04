"""Walkable graph built from OSM ways, with per-edge attributes used by the cost model.

Ways are split at junctions only, so each edge carries a single way's tags and
its full geometry; intermediate shape points are not graph nodes.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field

from .osm import OsmData

EARTH_M_PER_DEG_LAT = 110_540
EARTH_M_PER_DEG_LON_EQ = 111_320
GRID_M = 200.0  # cell size of the junction lookup grid

NATURE_HIGHWAYS = {"path", "track", "bridleway"}
UNPAVED = {
    "unpaved", "ground", "dirt", "earth", "grass", "gravel", "fine_gravel", "compacted",
    "mud", "sand", "woodchips", "pebblestone", "rock", "grass_paver",
}
# 0 = no motor traffic, 3 = main road.
TRAFFIC = {
    "primary": 3.0, "primary_link": 3.0, "secondary": 2.5, "secondary_link": 2.5,
    "tertiary": 2.0, "tertiary_link": 2.0, "unclassified": 1.0, "road": 1.0,
    "residential": 0.6, "service": 0.4, "living_street": 0.2,
}
# Probability of lighting when `lit` is not tagged (most ways): towns light streets, not trails.
LIT_GUESS = {
    "primary": 0.8, "secondary": 0.8, "tertiary": 0.7, "residential": 0.7, "living_street": 0.8,
    "pedestrian": 0.8, "unclassified": 0.4, "service": 0.4, "footway": 0.5, "cycleway": 0.5,
    "steps": 0.5, "path": 0.1, "track": 0.05, "bridleway": 0.05,
}


@dataclass
class Edge:
    u: int
    v: int
    nodes: list[int]  # OSM node ids from u to v
    length_m: float
    nature: float  # 1 = dirt trail
    traffic: float  # 0..3
    lit: float  # 0..1, estimated when untagged
    steps: bool
    way_tags: dict[str, str]
    familiar: float = 0.0  # share of the edge already run (0..1)
    climb_m: float = 0.0  # ascent going u -> v (the descent going v -> u)
    drop_m: float = 0.0  # descent going u -> v

    def ascent(self, reverse: bool) -> float:
        return self.drop_m if reverse else self.climb_m


@dataclass
class Graph:
    coords: dict[int, tuple[float, float]]  # node id -> (lat, lon), all shape points included
    edges: list[Edge] = field(default_factory=list)
    adj: dict[int, list[int]] = field(default_factory=dict)  # junction node -> edge indexes
    lat0: float = 45.0
    ele: dict[int, float] = field(default_factory=dict)  # node id -> elevation (m), when a DEM was applied

    def __post_init__(self) -> None:
        self._grid: dict[tuple[int, int], list[int]] | None = None  # built on first nearest_node()
        self.m_per_deg_lon = EARTH_M_PER_DEG_LON_EQ * math.cos(math.radians(self.lat0))

    def xy(self, node: int) -> tuple[float, float]:
        lat, lon = self.coords[node]
        return lon * self.m_per_deg_lon, lat * EARTH_M_PER_DEG_LAT

    def other(self, edge: Edge, node: int) -> int:
        return edge.v if edge.u == node else edge.u

    def nearest_node(self, lat: float, lon: float, max_m: float = 500.0, penalty=None) -> int | None:
        """Nearest junction node within `max_m`, looked up in a grid of junctions.

        `penalty(node) -> meters` is added to the distance, to favour some nodes.
        """
        k = self.m_per_deg_lon
        if self._grid is None:
            self._grid = {}
            for n in self.adj:
                nlat, nlon = self.coords[n]
                key = (int(nlon * k // GRID_M), int(nlat * EARTH_M_PER_DEG_LAT // GRID_M))
                self._grid.setdefault(key, []).append(n)
        cx, cy = int(lon * k // GRID_M), int(lat * EARTH_M_PER_DEG_LAT // GRID_M)
        r = int(max_m // GRID_M) + 1
        best, best_d = None, math.inf
        for i in range(cx - r, cx + r + 1):
            for j in range(cy - r, cy + r + 1):
                for n in self._grid.get((i, j), ()):
                    nlat, nlon = self.coords[n]
                    d2 = ((nlat - lat) * EARTH_M_PER_DEG_LAT) ** 2 + ((nlon - lon) * k) ** 2
                    if d2 > max_m**2:
                        continue
                    d = math.sqrt(d2) + (penalty(n) if penalty else 0.0)
                    if d < best_d:
                        best, best_d = n, d
        return best


def build_graph(osm: OsmData) -> Graph:
    ways = [(nodes, tags) for nodes, tags in osm.ways if _walkable(tags) and len(nodes) >= 2]
    usage = Counter(n for nodes, _ in ways for n in set(nodes))
    lats = [lat for lat, _ in osm.nodes.values()]
    g = Graph(coords=osm.nodes, lat0=sum(lats) / len(lats) if lats else 45.0)
    k = g.m_per_deg_lon
    for nodes, tags in ways:
        nodes = [n for n in nodes if n in osm.nodes]  # ways cut at the tile border lose far nodes
        attrs = _attributes(tags)
        start = 0
        for i in range(1, len(nodes)):
            if i == len(nodes) - 1 or usage[nodes[i]] > 1:
                seg = nodes[start : i + 1]
                if len(seg) >= 2 and seg[0] != seg[-1]:
                    length = sum(_dist(osm.nodes[a], osm.nodes[b], k) for a, b in zip(seg, seg[1:]))
                    g.edges.append(Edge(seg[0], seg[-1], seg, length, way_tags=tags, **attrs))
                    idx = len(g.edges) - 1
                    g.adj.setdefault(seg[0], []).append(idx)
                    g.adj.setdefault(seg[-1], []).append(idx)
                start = i
    return g


def add_elevation(g: Graph, dem) -> None:
    """Elevation of every graph point, and per-edge climb/drop (raw sums: the DEM is already smooth)."""
    import numpy as np

    ids = list({n for e in g.edges for n in e.nodes})
    if not ids:
        return
    lats = np.array([g.coords[n][0] for n in ids])
    lons = np.array([g.coords[n][1] for n in ids])
    g.ele = dict(zip(ids, dem.elevations(lats, lons).round(1).tolist()))
    for e in g.edges:
        zs = [g.ele[n] for n in e.nodes]
        diffs = [b - a for a, b in zip(zs, zs[1:])]
        e.climb_m = sum(d for d in diffs if d > 0)
        e.drop_m = -sum(d for d in diffs if d < 0)


def mark_familiar(g: Graph, tracks: list[list[tuple[float, float]]], tolerance_m: float = 12.0) -> None:
    """Set `edge.familiar` from the user's tracks ((lon, lat) polylines).

    Tracks are rasterized on a grid of `tolerance_m` cells; an edge sample counts
    as run when its cell or a neighbouring one was crossed by a track.
    """
    k, cell = g.m_per_deg_lon, tolerance_m
    crossed: set[tuple[int, int]] = set()
    for line in tracks:
        for (lon1, lat1), (lon2, lat2) in zip(line, line[1:]):
            x1, y1, x2, y2 = lon1 * k, lat1 * EARTH_M_PER_DEG_LAT, lon2 * k, lat2 * EARTH_M_PER_DEG_LAT
            steps = max(1, int(math.hypot(x2 - x1, y2 - y1) / (cell / 2)))
            for s in range(steps + 1):
                t = s / steps
                crossed.add((int((x1 + t * (x2 - x1)) // cell), int((y1 + t * (y2 - y1)) // cell)))
    for e in g.edges:
        samples = hits = 0
        for a, b in zip(e.nodes, e.nodes[1:]):
            (xa, ya), (xb, yb) = g.xy(a), g.xy(b)
            steps = max(1, int(math.hypot(xb - xa, yb - ya) / cell))
            for s in range(steps):
                t = s / steps
                cx, cy = int((xa + t * (xb - xa)) // cell), int((ya + t * (yb - ya)) // cell)
                samples += 1
                hits += any((cx + dx, cy + dy) in crossed for dx in (-1, 0, 1) for dy in (-1, 0, 1))
        e.familiar = hits / samples if samples else 0.0


def _walkable(tags: dict[str, str]) -> bool:
    if tags.get("foot") in ("no", "private") or tags.get("area") == "yes":
        return False
    if tags.get("access") in ("no", "private") and tags.get("foot") not in ("yes", "designated", "permissive"):
        return False
    return tags.get("highway") not in ("cycleway",) or tags.get("foot") in ("yes", "designated")


def _attributes(tags: dict[str, str]) -> dict:
    hw = tags.get("highway", "")
    surface = tags.get("surface", "")
    if surface in UNPAVED:
        nature = 1.0
    elif hw in NATURE_HIGHWAYS:
        nature = 0.2 if surface else 0.9  # an untagged path/track is usually dirt
    else:
        nature = 0.0
    traffic = TRAFFIC.get(hw, 0.0)
    if traffic and tags.get("maxspeed") in ("20", "30"):
        traffic *= 0.6
    lit_tag = tags.get("lit")
    lit = 1.0 if lit_tag in ("yes", "automatic", "24/7") else 0.0 if lit_tag == "no" else LIT_GUESS.get(hw, 0.3)
    return {"nature": nature, "traffic": traffic, "lit": lit, "steps": hw == "steps"}


def _dist(a: tuple[float, float], b: tuple[float, float], m_per_deg_lon: float) -> float:
    return math.hypot((a[0] - b[0]) * EARTH_M_PER_DEG_LAT, (a[1] - b[1]) * m_per_deg_lon)
