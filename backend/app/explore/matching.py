"""Which OSM path segments an activity went along (map-matching, first version).

A segment is an edge of the router's graph: the walkable OSM way between two junctions, the same paths as
the router. Its key comes from its OSM nodes, so it survives graph rebuilds (and will carry the ratings of
step 3).

How a track is matched:
1. Only what may be shown counts: the privacy-masked parts (200 m ends, privacy zones), and only between
   timestamped points at most 25 km/h apart (a bike ride, a car, a GPS jump are dropped).
   Sidewalks, crossings, driveways and parking aisles are left out: a track on a sidewalk snaps to its street.
2. The track is resampled every 5 m. Each sample snaps to a segment less than 20 m away whose direction
   agrees (within 45°, either way); among those, the segment of the previous sample or one sharing a node with
   it wins unless another is much closer (continuity: no hopping to the parallel street).
3. Each sample covers ±5 m along its segment. A segment is traversed when the covered stretches add up to
   80 % of its length: crossing a street or touching its end does not count, and an out-and-back covers the
   same stretches twice but counts once.
"""
from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from ..ingest.models import TrackPoint
from ..routing.graph import EARTH_M_PER_DEG_LAT, Edge, Graph

SNAP_M = 20.0
MAX_SPEED_MS = 25 / 3.6
STEP_M = 5.0
COVERED = 0.8
DIRECTION_DEG = 45.0
CONTINUITY_M = 6.0  # a non-continuous segment must be this much closer to win
CELL_M = 50.0


def explorable(e: Edge) -> bool:
    """Paths that count for exploration: the router's walkable ways, but not those drawn alongside a street
    (sidewalks, crossings: running there is running that street) nor driveways and parking aisles (a city
    street would otherwise count three times, and no commune could ever reach 100 %)."""
    t = e.way_tags
    return t.get("footway") not in ("sidewalk", "crossing", "traffic_island") and t.get("service") not in ("driveway", "parking_aisle", "drive-through")


def segment_key(nodes: Sequence[int]) -> str:
    """Stable id of an edge: its OSM end nodes and first inner node, the same whichever way it is read."""
    n = list(nodes) if nodes[0] <= nodes[-1] else list(reversed(nodes))
    return f"{n[0]}:{n[1]}:{n[-1]}"


def moving_parts(segments: Iterable[Sequence[TrackPoint]], max_speed_ms: float = MAX_SPEED_MS) -> list[list[TrackPoint]]:
    """Runs of consecutive timestamped points no faster than `max_speed_ms` between them."""
    out: list[list[TrackPoint]] = []
    for seg in segments:
        run: list[TrackPoint] = []
        for p in seg:
            if p.time is None:
                if len(run) >= 2:
                    out.append(run)
                run = []
                continue
            if run:
                q = run[-1]
                dt = (p.time - q.time).total_seconds()
                if dt <= 0 or _dist_m(q, p) / dt > max_speed_ms:
                    if len(run) >= 2:
                        out.append(run)
                    run = []
            run.append(p)
        if len(run) >= 2:
            out.append(run)
    return out


@dataclass
class _Piece:
    edge: int
    start_m: float  # distance from the edge's first node to this piece's start
    ax: float
    ay: float
    bx: float
    by: float


class EdgeIndex:
    """The graph's edges cut into straight pieces, in a grid, for "which edges are near this point"."""

    def __init__(self, g: Graph):
        self.g = g
        self.k = g.m_per_deg_lon
        self.grid: dict[tuple[int, int], list[_Piece]] = defaultdict(list)
        self.length: list[float] = []
        for idx, e in enumerate(g.edges):
            if not explorable(e):
                self.length.append(0.0)
                continue
            done = 0.0
            pts = [self._xy(n) for n in e.nodes]
            for (ax, ay), (bx, by) in zip(pts, pts[1:]):
                piece = _Piece(idx, done, ax, ay, bx, by)
                for cell in self._cells(ax, ay, bx, by):
                    self.grid[cell].append(piece)
                done += math.hypot(bx - ax, by - ay)
            self.length.append(done)

    def _xy(self, node: int) -> tuple[float, float]:
        lat, lon = self.g.coords[node]
        return lon * self.k, lat * EARTH_M_PER_DEG_LAT

    def _cells(self, ax, ay, bx, by):
        x0, x1 = sorted((ax, bx))
        y0, y1 = sorted((ay, by))
        for i in range(math.floor(x0 / CELL_M), math.floor(x1 / CELL_M) + 1):
            for j in range(math.floor(y0 / CELL_M), math.floor(y1 / CELL_M) + 1):
                yield i, j

    def near(self, x: float, y: float, within: float) -> list[tuple[float, float, int, float]]:
        """(distance, position along the edge, edge, piece bearing) of the pieces within `within`, per edge the closest."""
        best: dict[int, tuple[float, float, int, float]] = {}
        ci, cj = math.floor(x / CELL_M), math.floor(y / CELL_M)
        for i in (ci - 1, ci, ci + 1):
            for j in (cj - 1, cj, cj + 1):
                for p in self.grid.get((i, j), ()):
                    dx, dy = p.bx - p.ax, p.by - p.ay
                    seg = dx * dx + dy * dy
                    t = 0.0 if seg == 0 else max(0.0, min(1.0, ((x - p.ax) * dx + (y - p.ay) * dy) / seg))
                    d = math.hypot(x - (p.ax + t * dx), y - (p.ay + t * dy))
                    if d <= within and (p.edge not in best or d < best[p.edge][0]):
                        best[p.edge] = (d, p.start_m + t * math.sqrt(seg), p.edge, math.degrees(math.atan2(dx, dy)))
        return sorted(best.values())


def traversed_edges(g: Graph, parts: Sequence[Sequence[TrackPoint]], index: EdgeIndex | None = None) -> dict[int, float]:
    """Edge index -> covered share of its length (only those covered to `COVERED`) for these track parts."""
    index = index or EdgeIndex(g)
    covered: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for part in parts:
        samples = _resample(part, index.k)
        prev: int | None = None
        for (x, y), heading in samples:
            cands = [c for c in index.near(x, y, SNAP_M) if _agrees(c[3], heading)]
            if not cands:
                prev = None
                continue
            choice = cands[0]
            if prev is not None:
                for c in cands:
                    if _continues(g, prev, c[2]) and c[0] <= cands[0][0] + CONTINUITY_M:
                        choice = c
                        break
            covered[choice[2]].append((choice[1] - STEP_M, choice[1] + STEP_M))
            prev = choice[2]
    out = {}
    for edge, stretches in covered.items():
        length = index.length[edge]
        if length <= 0:
            continue
        share = _union(stretches, length) / length
        if share >= COVERED:
            out[edge] = round(min(share, 1.0), 3)
    return out


def _resample(part: Sequence[TrackPoint], k: float) -> list[tuple[tuple[float, float], float]]:
    """Points every STEP_M along the track, with the track's heading there (degrees from north)."""
    pts = [(p.lon * k, p.lat * EARTH_M_PER_DEG_LAT) for p in part]
    out = []
    carry = 0.0
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        seg = math.hypot(bx - ax, by - ay)
        if seg == 0:
            continue
        heading = math.degrees(math.atan2(bx - ax, by - ay))
        d = carry
        while d < seg:
            t = d / seg
            out.append(((ax + t * (bx - ax), ay + t * (by - ay)), heading))
            d += STEP_M
        carry = d - seg
    return out


def _agrees(piece_bearing: float, heading: float) -> bool:
    diff = abs((piece_bearing - heading + 180) % 360 - 180)
    return min(diff, 180 - diff) <= DIRECTION_DEG


def _continues(g: Graph, a: int, b: int) -> bool:
    if a == b:
        return True
    ea, eb = g.edges[a], g.edges[b]
    return bool({ea.u, ea.v} & {eb.u, eb.v})


def _union(stretches: list[tuple[float, float]], length: float) -> float:
    total = 0.0
    end = -math.inf
    for a, b in sorted((max(0.0, a), min(length, b)) for a, b in stretches):
        if b <= end:
            continue
        total += b - max(a, end)
        end = b
    return total


def _dist_m(a: TrackPoint, b: TrackPoint) -> float:
    k = 111_320 * math.cos(math.radians((a.lat + b.lat) / 2))
    return math.hypot((a.lon - b.lon) * k, (a.lat - b.lat) * EARTH_M_PER_DEG_LAT)


def edge_midpoint(g: Graph, e: Edge) -> tuple[float, float]:
    """(lat, lon) halfway along the edge."""
    pts = [g.coords[n] for n in e.nodes]
    half = e.length_m / 2
    done = 0.0
    k = g.m_per_deg_lon
    for (alat, alon), (blat, blon) in zip(pts, pts[1:]):
        seg = math.hypot((blon - alon) * k, (blat - alat) * EARTH_M_PER_DEG_LAT)
        if done + seg >= half and seg > 0:
            t = (half - done) / seg
            return alat + t * (blat - alat), alon + t * (blon - alon)
        done += seg
    return pts[len(pts) // 2]
