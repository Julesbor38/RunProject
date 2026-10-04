"""How many distinct activities went along each piece of the user's tracks.

No map-matching yet (step 2): tracks are rasterized on a grid of CELL_M cells.
Each activity counts once per cell, so an out-and-back within one activity is a
single pass. GPS drift (±5-15 m) is absorbed by widening every activity's cells
to their 8 neighbours before counting: two runs on the same path, a cell apart,
add up on the cells of both.

Each path is drawn once, as one continuous line: tracks are laid from the most
representative (along the busiest paths) down, keeping only their parts away from
what is already drawn (DRAWN_CELLS around it: the same path, GPS aside). That
single network is then cut into pieces of constant pass level, which the map
draws from light and thin (1 pass) to dark and thick (many passes).
Inputs are the already privacy-masked tracks of /api/activities, so masked parts
never show.
"""
from __future__ import annotations

import math
from collections import Counter, deque
from statistics import median

from .routing.graph import EARTH_M_PER_DEG_LAT, EARTH_M_PER_DEG_LON_EQ

CELL_M = 12.0
SAMPLE_M = CELL_M / 2  # sampling step along tracks: never skips a cell
SMOOTH = 21  # rolling median window (samples are 3-6 m apart: 60-125 m), so a crossing
# path (~36 m of widened cells at right angles) leaves no darker blip on the track
LEVELS = (1, 2, 3, 5, 10, 20, 50)  # lower bounds of the drawn pass levels
# Dedup of the drawing. A track running within DRAWN_CELLS cells (~30 m) of a drawn line is the
# same path (GPS drift in streets reaches 20-30 m); then, in samples (3-6 m apart):
DRAWN_CELLS = 2
SELF_LAG = 12  # a piece only hides itself behind its samples this far back (out-and-back legs)
MIN_GAP = 24  # a shorter run over drawn cells (a crossing: ~60 m of them) does not cut the new line
MIN_RUN = 12  # a shorter run off drawn cells (GPS wobble beside a path) is not drawn
JOIN = 6  # drawn runs reach this far into drawn cells, to connect to the existing line
SPORTS = ("run", "trail_run", "hike")
VERSION = 4  # bump to invalidate the cache when the algorithm changes
# Cached results are reused only when computed with the very same settings.
SIGNATURE = (
    f"v{VERSION} cell={CELL_M} sample={SAMPLE_M} smooth={SMOOTH} levels={LEVELS}"
    f" dedup={DRAWN_CELLS},{SELF_LAG},{MIN_GAP},{MIN_RUN},{JOIN}"
)

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


def widen(cells, r: int = 1) -> set[tuple[int, int]]:
    """Cells plus their neighbours up to `r` cells away (r=1: the 8 neighbours)."""
    near = range(-r, r + 1)
    return {(x + dx, y + dy) for x, y in cells for dx in near for dy in near}


def activity_cells(lines: list[Line], grid: Grid) -> set[tuple[int, int]]:
    """Cells an activity went through, widened by one cell for GPS drift."""
    return widen({grid.cell_of(lon, lat) for line in lines for _, _, lon, lat in grid.samples(line)})


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


def _runs(flags: list[bool]) -> list[tuple[bool, int, int]]:
    """(value, start, end excluded) for each run of equal flags."""
    out, i = [], 0
    while i < len(flags):
        j = i
        while j < len(flags) and flags[j] == flags[i]:
            j += 1
        out.append((flags[i], i, j))
        i = j
    return out


def _fill(flags: list[bool], value: bool, shorter_than: int) -> list[bool]:
    """Runs of `value` shorter than `shorter_than` take the opposite value (not at the ends)."""
    flags = flags[:]
    runs = _runs(flags)
    for k, (v, i, j) in enumerate(runs):
        if v == value and j - i < shorter_than and 0 < k < len(runs) - 1:
            flags[i:j] = [not value] * (j - i)
    return flags


def undrawn_parts(line: Line, drawn: set[tuple[int, int]], grid: Grid) -> list[Line]:
    """Parts of `line` not already drawn; `drawn` grows with the widened cells of what is kept.

    A part reaches JOIN samples into the drawn cells on both sides so it meets the
    existing line. The line hides behind its own earlier samples too (SELF_LAG back),
    so the way back of an out-and-back is not drawn beside the way out.
    """
    samples = grid.samples(line)
    cells = [grid.cell_of(lon, lat) for _, _, lon, lat in samples]
    own: set[tuple[int, int]] = set()
    lagging: deque = deque()
    new = []
    for c in cells:
        new.append(c not in drawn and c not in own)
        lagging.append(c)
        if len(lagging) > SELF_LAG:
            own |= widen([lagging.popleft()], DRAWN_CELLS)
    new = _fill(new, False, MIN_GAP)  # crossing a drawn path does not cut the line
    new = _fill(new, True, MIN_RUN)  # neither does a short wobble off a drawn path
    parts = []
    for v, i, j in _runs(new):
        if not v or j - i < MIN_RUN:
            continue
        i, j = max(0, i - JOIN), min(len(samples), j + JOIN)
        part = [[round(samples[k][2], 6), round(samples[k][3], 6)] for k in range(i, j) if k in (i, j - 1) or samples[k][1] == 0]
        if len(part) >= 2:
            parts.append(part)
        drawn |= widen(cells[i:j], DRAWN_CELLS)
    return parts


def frequency_collection(fc: dict) -> dict:
    """Each path once, with its count of distinct activities; busiest drawn last.

    Pieces carry one activity that went there (for the click) and, per sport,
    whether activities of that sport went there (for the sport filters).
    """
    lats = [lat for f in fc["features"] for line in f["geometry"]["coordinates"] for _, lat in line]
    grid = Grid(sum(lats) / len(lats) if lats else 45.0)
    counts: Counter = Counter()
    sports: dict[tuple[int, int], set[str]] = {}
    for f in fc["features"]:
        cells = activity_cells(f["geometry"]["coordinates"], grid)
        counts.update(cells)
        for c in cells:
            sports.setdefault(c, set()).add(f["properties"].get("sport"))

    def busyness(line: Line) -> float:
        cells = [grid.cell_of(lon, lat) for _, _, lon, lat in grid.samples(line)]
        return sum(counts[c] for c in cells) / len(cells)

    # The tracks along the busiest paths draw them; the others only add what they alone went along.
    tracks = [(f, line) for f in fc["features"] for line in f["geometry"]["coordinates"] if len(line) >= 2]
    tracks.sort(key=lambda t: (-busyness(t[1]), -len(t[1])))
    drawn: set[tuple[int, int]] = set()
    features = []
    for f, line in tracks:
        for part in undrawn_parts(line, drawn, grid):
            for passes, piece in split_by_passes(part, counts, grid):
                cells = [grid.cell_of(lon, lat) for _, _, lon, lat in grid.samples(piece)]
                props = {"activity": f["id"], "passes": passes}
                for sport in SPORTS:
                    # A sport counts when it went along most of the piece (not just across it).
                    props[sport] = 2 * sum(sport in sports.get(c, ()) for c in cells) >= len(cells)
                features.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": piece}, "properties": props})
    features.sort(key=lambda feat: feat["properties"]["passes"])  # busiest drawn last, on top
    return {
        "type": "FeatureCollection",
        "features": features,
        "max_passes": max(counts.values(), default=0),
        "levels": list(LEVELS),
        "sports": list(SPORTS),
        "signature": SIGNATURE,
    }
