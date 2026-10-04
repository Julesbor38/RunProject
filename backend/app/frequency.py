"""How many distinct activities went along each piece of the user's tracks.

No map-matching yet (step 2): tracks are rasterized on a grid of CELL_M cells.
Each activity counts once per cell, so an out-and-back within one activity is a
single pass. GPS drift (±5-15 m) is absorbed by widening every activity's cells
to their 8 neighbours before counting: two runs on the same path, a cell apart,
add up on the cells of both.

Tracks are then cut into pieces of constant pass level, which the map draws
from light and thin (1 pass) to dark and thick (many passes). Inputs are the
already privacy-masked tracks of /api/activities, so masked parts never show.
"""
from __future__ import annotations

import math
from collections import Counter
from statistics import median

from .routing.graph import EARTH_M_PER_DEG_LAT, EARTH_M_PER_DEG_LON_EQ

CELL_M = 12.0
SAMPLE_M = CELL_M / 2  # sampling step along tracks: never skips a cell
SMOOTH = 21  # rolling median window (samples are 3-6 m apart: 60-125 m), so a crossing
# path (~36 m of widened cells at right angles) leaves no darker blip on the track
LEVELS = (1, 2, 3, 5, 10, 20, 50)  # lower bounds of the drawn pass levels
VERSION = 1  # bump to invalidate the cache when the algorithm changes
# Cached results are reused only when computed with the very same settings.
SIGNATURE = f"v{VERSION} cell={CELL_M} sample={SAMPLE_M} smooth={SMOOTH} levels={LEVELS}"

Line = list[list[float]]  # [[lon, lat], ...]


class Grid:
    """Local metric projection (equirectangular around `lat0`) and cell lookup."""

    def __init__(self, lat0: float, cell_m: float = CELL_M):
        self.kx = EARTH_M_PER_DEG_LON_EQ * math.cos(math.radians(lat0))
        self.cell = cell_m

    def cell_of(self, lon: float, lat: float) -> tuple[int, int]:
        return int(lon * self.kx // self.cell), int(lat * EARTH_M_PER_DEG_LAT // self.cell)

    def samples(self, line: Line) -> list[tuple[int, int, float, float]]:
        """(segment index, step, lon, lat) every SAMPLE_M along the line, vertices included."""
        out = []
        for i, ((lon1, lat1), (lon2, lat2)) in enumerate(zip(line, line[1:])):
            dist = math.hypot((lon2 - lon1) * self.kx, (lat2 - lat1) * EARTH_M_PER_DEG_LAT)
            steps = max(1, math.ceil(dist / SAMPLE_M))
            for s in range(steps):
                t = s / steps
                out.append((i, s, lon1 + t * (lon2 - lon1), lat1 + t * (lat2 - lat1)))
        if line:
            out.append((len(line) - 1, 0, *line[-1]))
        return out


def activity_cells(lines: list[Line], grid: Grid) -> set[tuple[int, int]]:
    """Cells an activity went through, widened by one cell for GPS drift."""
    cells = {grid.cell_of(lon, lat) for line in lines for _, _, lon, lat in grid.samples(line)}
    return {(x + dx, y + dy) for x, y in cells for dx in (-1, 0, 1) for dy in (-1, 0, 1)}


def pass_counts(activities: list[list[Line]], grid: Grid) -> Counter:
    """Cell -> number of distinct activities that went through it (or next to it)."""
    counts: Counter = Counter()
    for lines in activities:
        counts.update(activity_cells(lines, grid))
    return counts


def level(passes: float) -> int:
    """Lower bound of the LEVELS bucket holding `passes`."""
    return max((lv for lv in LEVELS if lv <= passes), default=1)


def split_by_passes(line: Line, counts: Counter, grid: Grid) -> list[tuple[int, Line]]:
    """Cut a track into (passes, piece) where the smoothed pass level stays the same.

    Pieces keep the track's own vertices, plus a cut point where the level changes;
    `passes` is the median count along the piece.
    """
    samples = grid.samples(line)
    if len(samples) < 2:
        return []
    raw = [counts.get(grid.cell_of(lon, lat), 1) for _, _, lon, lat in samples]
    half = SMOOTH // 2
    smooth = [median(raw[max(0, i - half) : i + half + 1]) for i in range(len(raw))]
    pieces: list[tuple[int, Line]] = []
    piece: Line = [[round(samples[0][2], 6), round(samples[0][3], 6)]]
    piece_counts = [smooth[0]]
    for k in range(1, len(samples)):
        seg, step, lon, lat = samples[k]
        point = [round(lon, 6), round(lat, 6)]
        if level(smooth[k]) != level(smooth[k - 1]):
            piece.append(point)  # the piece ends where the next one starts: no gap
            pieces.append((round(median(piece_counts)), piece))
            piece, piece_counts = [point], []
        elif step == 0:  # an original vertex
            piece.append(point)
        piece_counts.append(smooth[k])
    if len(piece) >= 2:
        pieces.append((round(median(piece_counts)), piece))
    return pieces


def frequency_collection(fc: dict) -> dict:
    """Pieces of every activity's (masked) tracks with their pass count, busiest drawn last."""
    lats = [lat for f in fc["features"] for line in f["geometry"]["coordinates"] for _, lat in line]
    grid = Grid(sum(lats) / len(lats) if lats else 45.0)
    counts = pass_counts([f["geometry"]["coordinates"] for f in fc["features"]], grid)
    features = []
    for f in fc["features"]:
        for line in f["geometry"]["coordinates"]:
            for passes, piece in split_by_passes(line, counts, grid):
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": piece},
                    "properties": {"activity": f["id"], "sport": f["properties"].get("sport"), "passes": passes},
                })
    features.sort(key=lambda feat: feat["properties"]["passes"])
    return {
        "type": "FeatureCollection",
        "features": features,
        "max_passes": max(counts.values(), default=0),
        "levels": list(LEVELS),
        "signature": SIGNATURE,
    }
