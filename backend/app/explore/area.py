"""Area discovered: a corridor 20 m wide on each side of the paths actually run, on a fixed grid of ~10 m cells.

The grid is the same for every activity and every user (cells are integers: a new activity only adds the cells
not seen yet, and two users can be compared later). Its x step is 10 m at 46.5°N (the middle of France), so a
cell is a little wider in the south and narrower in the north: its true area is kept with it.
A cell is discovered when its centre lies within 20 m of a point of the track (the privacy-masked, moving
parts, as for the paths), sampled every 5 m. It belongs to the commune its centre lies in.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

import numpy as np

from ..ingest.models import TrackPoint

CELL_M = 10.0
CORRIDOR_M = 20.0
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
    """Points every STEP_M (true metres) along the polyline, its ends included."""
    seg = pts[1:] - pts[:-1]
    lengths = np.hypot(seg[:, 0] * f, seg[:, 1])
    cum = np.concatenate([[0.0], np.cumsum(lengths)])
    if cum[-1] == 0:
        return pts[:1]
    at = np.append(np.arange(0.0, cum[-1], STEP_M), cum[-1])
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
