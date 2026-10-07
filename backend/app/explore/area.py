"""Area discovered: a corridor 50 m wide on each side of the paths actually run, on a fixed grid of ~10 m cells.

The grid is the same for every activity and every user (cells are integers: a new activity only adds the cells
not seen yet, and two users can be compared later). Its x step is 10 m at 46.5°N (the middle of France), so a
cell is a little wider in the south and narrower in the north: its true area is kept with it.
A cell is discovered when its centre lies within 50 m of a point of the track (the privacy-masked, moving
parts, as for the paths), sampled every 5 m. It belongs to the commune its centre lies in.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

import numpy as np

from ..ingest.models import TrackPoint

CELL_M = 10.0
CORRIDOR_M = 50.0
STEP_M = 5.0
M_PER_DEG = 111_320.0
REF_COS = math.cos(math.radians(46.5))
_R = math.ceil(CORRIDOR_M / CELL_M) + 1
_OFFSETS = np.array([(i, j) for i in range(-_R, _R + 1) for j in range(-_R, _R + 1)])  # cells around a sample


def to_grid(lat: float, lon: float) -> tuple[float, float]:
    """Grid metres (x, y) of a point."""
    return lon * M_PER_DEG * REF_COS, lat * M_PER_DEG


def cell_center(cx: int, cy: int) -> tuple[float, float]:
    """(lat, lon) of a cell's centre."""
    return (cy + 0.5) * CELL_M / M_PER_DEG, (cx + 0.5) * CELL_M / (M_PER_DEG * REF_COS)


def cell_area(cy: int) -> float:
    """True area (m²) of the cells of this row."""
    lat = (cy + 0.5) * CELL_M / M_PER_DEG
    return CELL_M * CELL_M * math.cos(math.radians(lat)) / REF_COS


def corridor_cells(parts: Iterable[Sequence[TrackPoint]]) -> set[tuple[int, int]]:
    """Cells whose centre is within CORRIDOR_M of the track parts."""
    out: set[tuple[int, int]] = set()
    for part in parts:
        if len(part) < 2:
            continue
        f = math.cos(math.radians(part[0].lat)) / REF_COS  # true metres per grid metre along x, here
        pts = np.array([to_grid(p.lat, p.lon) for p in part])
        samples = _resample(pts, f)
        base = np.floor(samples / CELL_M).astype(np.int64)
        cells = base[:, None, :] + _OFFSETS[None, :, :]  # (samples, offsets, 2)
        centers = (cells + 0.5) * CELL_M
        d = centers - samples[:, None, :]
        near = (d[..., 0] * f) ** 2 + d[..., 1] ** 2 <= CORRIDOR_M**2
        out.update(map(tuple, np.unique(cells[near], axis=0).tolist()))
    return out


def _resample(pts: np.ndarray, f: float) -> np.ndarray:
    """Points every STEP_M (true metres) along the polyline, and its own points (its ends, its turns)."""
    seg = pts[1:] - pts[:-1]
    lengths = np.hypot(seg[:, 0] * f, seg[:, 1])
    cum = np.concatenate([[0.0], np.cumsum(lengths)])
    if cum[-1] == 0:
        return pts[:1]
    at = np.union1d(np.arange(0.0, cum[-1], STEP_M), cum)
    return np.column_stack([np.interp(at, cum, pts[:, 0]), np.interp(at, cum, pts[:, 1])])


def in_polygons(lats: np.ndarray, lons: np.ndarray, polygons: list) -> np.ndarray:
    """Which points lie in these polygons ([[outer ring, hole, …], …] of [lon, lat]), vectorised."""
    inside = np.zeros(len(lats), dtype=bool)
    for poly in polygons:
        hit = _in_ring(lats, lons, poly[0])
        for hole in poly[1:]:
            hit &= ~_in_ring(lats, lons, hole)
        inside |= hit
    return inside


def _in_ring(lats: np.ndarray, lons: np.ndarray, ring: list, chunk: int = 2000) -> np.ndarray:
    r = np.asarray(ring, dtype=float)
    x1, y1 = r[:, 0], r[:, 1]
    x2, y2 = np.roll(x1, -1), np.roll(y1, -1)
    dy = np.where(y2 == y1, 1e-12, y2 - y1)
    out = np.zeros(len(lats), dtype=bool)
    for s in range(0, len(lats), chunk):
        la, lo = lats[s : s + chunk, None], lons[s : s + chunk, None]
        crosses = ((y1 > la) != (y2 > la)) & (lo < x1 + (la - y1) * (x2 - x1) / dy)
        out[s : s + chunk] = np.count_nonzero(crosses, axis=1) % 2 == 1
    return out


def polygons_area(polygons: list) -> float:
    """Area (m²) of [[outer ring, hole, …], …] of [lon, lat]."""
    total = 0.0
    for poly in polygons:
        for i, ring in enumerate(poly):
            a = _ring_area(ring)
            total += a if i == 0 else -a
    return total


def _ring_area(ring: list) -> float:
    r = np.asarray(ring, dtype=float)
    k = M_PER_DEG * math.cos(math.radians(float(r[:, 1].mean())))
    x, y = r[:, 0] * k, r[:, 1] * M_PER_DEG
    return abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))) / 2


# --- the « Brouillard »: a veil over the map with the discovered area cut out ---

WORLD = [[-180.0, -85.0], [180.0, -85.0], [180.0, 85.0], [-180.0, 85.0], [-180.0, -85.0]]


def block_for_zoom(zoom: float) -> int:
    """Cells merged into blocks when zoomed out (10 m at 14+, 20 m at 13, 40 m at 12, 80 m at 11, 160 m below);
    the smoothing hides the steps."""
    return 1 << max(0, min(4, 14 - math.floor(zoom)))


def grid_range(bbox: Sequence[float]) -> tuple[int, int, int, int]:
    """(cx0, cx1, cy0, cy1) of the cells over a [min_lon, min_lat, max_lon, max_lat] box."""
    x0, y0 = to_grid(bbox[1], bbox[0])
    x1, y1 = to_grid(bbox[3], bbox[2])
    return math.floor(x0 / CELL_M), math.floor(x1 / CELL_M), math.floor(y0 / CELL_M), math.floor(y1 / CELL_M)


def veil(cells: Iterable[tuple[int, int]], block: int = 1) -> dict:
    """GeoJSON MultiPolygon of the veil: the world minus the discovered cells (merged into `block`×`block`), the
    undiscovered pockets inside a discovered area veiled again. The outlines are smoothed into round shapes (like
    the corridor around a path really is), not the cells' steps. Rings are wound for MapLibre: outer rings one way,
    holes the other."""
    blocks = {(cx // block, cy // block) for cx, cy in cells}
    size = CELL_M * block

    def lonlat(ring):
        return [[round(x * size / (M_PER_DEG * REF_COS), 5), round(y * size / M_PER_DEG, 5)] for x, y in ring]

    rings = [_smooth(_simplify(r, 0.9)) for r in _outlines(blocks)]
    rings = [r for r in rings if len(r) >= 4]
    areas = [_signed_area(r) for r in rings]
    regions = [r for r, a in zip(rings, areas) if a > 0]  # counter-clockwise: the edge of a discovered area
    # clockwise: an undiscovered pocket inside one (specks of a block or two, between close passes, are not shown)
    pockets = [r for r, a in zip(rings, areas) if a < -2.5]
    polygons = [[WORLD] + [lonlat(r) for r in regions]]  # world counter-clockwise, regions as clockwise holes:
    polygons[0][1:] = [ring[::-1] for ring in polygons[0][1:]]
    for pocket in pockets:
        islands = [r for r in regions if _in_grid_ring(r[0], pocket)]
        polygons.append([lonlat(pocket[::-1])] + [lonlat(r)[::-1] for r in islands])
    return {"type": "Feature", "geometry": {"type": "MultiPolygon", "coordinates": polygons}, "properties": {}}


def _outlines(blocks: set[tuple[int, int]]) -> list[list[tuple[int, int]]]:
    """Closed rings (grid vertices) around the blocks, each block on the left: areas counter-clockwise,
    holes clockwise. Where two blocks touch only by a corner, the ring turns left (keeps to its block)."""
    out: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for i, j in blocks:
        if (i, j - 1) not in blocks:
            out.setdefault((i, j), []).append((i + 1, j))
        if (i + 1, j) not in blocks:
            out.setdefault((i + 1, j), []).append((i + 1, j + 1))
        if (i, j + 1) not in blocks:
            out.setdefault((i + 1, j + 1), []).append((i, j + 1))
        if (i - 1, j) not in blocks:
            out.setdefault((i, j + 1), []).append((i, j))
    rings = []
    while out:
        start = next(iter(out))
        ring = [start]
        a, b = start, out[start].pop()
        if not out[start]:
            del out[start]
        while b != start:
            ring.append(b)
            nexts = out[b]
            dx, dy = b[0] - a[0], b[1] - a[1]
            # left turn first, then straight, then right
            order = {(-dy, dx): 0, (dx, dy): 1, (dy, -dx): 2}
            c = min(nexts, key=lambda n: order.get((n[0] - b[0], n[1] - b[1]), 3))
            nexts.remove(c)
            if not nexts:
                del out[b]
            a, b = b, c
        ring.append(start)
        rings.append(_drop_collinear(ring))
    return rings


def _drop_collinear(ring: list[tuple[int, int]]) -> list[tuple[float, float]]:
    pts = ring[:-1]
    keep = [p for k, p in enumerate(pts)
            if (p[0] - pts[k - 1][0]) * (pts[(k + 1) % len(pts)][1] - p[1]) != (p[1] - pts[k - 1][1]) * (pts[(k + 1) % len(pts)][0] - p[0])]
    return keep + keep[:1]


def _simplify(ring: list, tolerance: float) -> list:
    """Douglas-Peucker on a closed ring (grid units): smooths the staircases of diagonal paths."""
    if len(ring) <= 5:
        return ring
    far = max(range(len(ring)), key=lambda k: (ring[k][0] - ring[0][0]) ** 2 + (ring[k][1] - ring[0][1]) ** 2)
    return _dp(ring[: far + 1], tolerance)[:-1] + _dp(ring[far:], tolerance)


def _dp(pts: list, tolerance: float) -> list:
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = pts[a], pts[b]
        dx, dy = bx - ax, by - ay
        norm = math.hypot(dx, dy)
        best, at = 0.0, -1
        for k in range(a + 1, b):
            px, py = pts[k]
            d = abs(dy * (px - ax) - dx * (py - ay)) / norm if norm else math.hypot(px - ax, py - ay)
            if d > best:
                best, at = d, k
        if best > tolerance:
            keep[at] = True
            stack += [(a, at), (at, b)]
    return [p for p, k in zip(pts, keep) if k]


def _smooth(ring: list, rounds: int = 3) -> list:
    """Chaikin corner cutting on a closed ring: every corner becomes a curve."""
    if len(ring) < 4:
        return ring
    pts = ring[:-1]
    for _ in range(rounds):
        nxt = []
        for k, (ax, ay) in enumerate(pts):
            bx, by = pts[(k + 1) % len(pts)]
            nxt += [(0.75 * ax + 0.25 * bx, 0.75 * ay + 0.25 * by), (0.25 * ax + 0.75 * bx, 0.25 * ay + 0.75 * by)]
        pts = nxt
    return pts + pts[:1]


def _signed_area(ring: list) -> float:
    return sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:])) / 2


def _in_grid_ring(p, ring: list) -> bool:
    x, y = p
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside
