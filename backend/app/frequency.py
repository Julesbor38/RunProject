"""How many distinct activities went along each street / path, drawn on the map.

Counting: tracks are rasterized on a grid of CELL_M cells. Each activity counts
once per cell, so an out-and-back within one activity is a single pass. GPS drift
(±5-15 m) is absorbed by widening every activity's cells to their 8 neighbours.

Drawing, on OpenStreetMap ways (the streets and paths themselves, not the GPS lines):
ways are cut in chunks of ~CHUNK samples; an activity passed along a chunk when its
widened cells hold at least ALONG of the chunk (merely crossing it does not count).
Chunks with passes are merged into pieces of constant pass level. Where a road and
its sidewalk are both mapped, only the way the GPS points actually fall on is kept
(highest `fit`, the others are within its widened cells).
Where no OSM way explains a track (tile not downloaded yet, path missing from OSM),
the track itself is drawn, once per path (tracks laid from the most representative
down, keeping only their parts away from what is already drawn).

Inputs are the already privacy-masked tracks of /api/activities, so masked parts
never show (OSM pieces only exist where masked tracks went).
"""
from __future__ import annotations

import math
from collections import Counter, deque
from statistics import median

from .routing.graph import EARTH_M_PER_DEG_LAT, EARTH_M_PER_DEG_LON_EQ, _walkable
from .routing.osm import OsmData

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
# OSM ways, in samples along the way:
CHUNK = 8  # pass counts are evaluated on chunks this long (25-50 m)
ALONG = 0.6  # an activity passed along a chunk when its widened cells hold this share of it
OSM_MIN_RUN = 10  # shorter leftovers of a way beside a drawn one (the start of a side street) are not drawn
OSM_JOIN = 8  # a way reaches this far into drawn cells: up to the junction with the drawn way
COARSE = 8  # coarse cells (x CELL_M) to skip quickly the ways far from any track
SPORTS = ("run", "trail_run", "hike")
VERSION = 8  # bump to invalidate the cache when the algorithm changes
# Cached results are reused only when computed with the very same settings.
SIGNATURE = (
    f"v{VERSION} cell={CELL_M} sample={SAMPLE_M} smooth={SMOOTH} levels={LEVELS}"
    f" dedup={DRAWN_CELLS},{SELF_LAG},{MIN_GAP},{MIN_RUN},{JOIN}"
    f" osm={CHUNK},{ALONG},{OSM_MIN_RUN},{OSM_JOIN}"
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


Drawn = dict[tuple[int, int], list]  # cell -> (street key, heading) of the lines drawn through it
PARALLEL = math.radians(35)  # a drawn line hides another one only when they run this parallel


def _headings(line: Line, samples: list, grid: Grid) -> list[float]:
    """Direction (radians, modulo pi) of the line at each sample."""
    out = []
    for seg, _, _, _ in samples:
        i = min(seg, len(line) - 2)
        (lon1, lat1), (lon2, lat2) = line[i], line[i + 1]
        out.append(math.atan2((lat2 - lat1) * EARTH_M_PER_DEG_LAT, (lon2 - lon1) * grid.kx) % math.pi)
    return out


def _hides(entries: list | None, key, heading: float) -> bool:
    """Whether lines drawn through a cell hide a line of `key` going `heading` there."""
    for k, h in entries or ():
        d = abs(h - heading) % math.pi
        if min(d, math.pi - d) < PARALLEL and (key is None or k != key):
            return True
    return False


def undrawn_parts(
    line: Line,
    drawn: Drawn,
    grid: Grid,
    *,
    key=None,
    self_lag: int | None = SELF_LAG,
    r: int = DRAWN_CELLS,
    min_run: int = MIN_RUN,
    join: int = JOIN,
) -> list[Line]:
    """Parts of `line` not already drawn; `drawn` grows with the cells (widened by `r`) of what is kept.

    Only lines running parallel hide each other (a sidewalk, the same path with GPS drift):
    crossing streets do not. With a `key` (a street's name and type), lines of that same
    street do not hide it either: both carriageways of an avenue are drawn. A part reaches
    `join` samples into the drawn cells on both sides so it meets the existing line. With
    `self_lag`, the line hides behind its own samples that far back too, so the way back
    of an out-and-back is not drawn beside the way out.
    """
    if len(line) < 2:
        return []
    samples = grid.samples(line)
    cells = [grid.cell_of(lon, lat) for _, _, lon, lat in samples]
    headings = _headings(line, samples, grid)
    own: set[tuple[int, int]] = set()
    lagging: deque = deque()
    new = []
    for c, h in zip(cells, headings):
        new.append(not _hides(drawn.get(c), key, h) and c not in own)
        if self_lag is not None:
            lagging.append(c)
            if len(lagging) > self_lag:
                own |= widen([lagging.popleft()], r)
    new = _fill(new, False, MIN_GAP)  # crossing a drawn path does not cut the line
    new = _fill(new, True, min_run)  # neither does a short wobble off a drawn path
    parts = []
    for v, i, j in _runs(new):
        if not v or j - i < min_run:
            continue
        i, j = max(0, i - join), min(len(samples), j + join)
        part = [[round(samples[k][2], 6), round(samples[k][3], 6)] for k in range(i, j) if k in (i, j - 1) or samples[k][1] == 0]
        if len(part) >= 2:
            parts.append(part)
        for k in range(i, j):
            for c in widen([cells[k]], r):
                drawn.setdefault(c, []).append((key, headings[k]))
    return parts


# Mapped beside / across a street: drawing them would double or break the street's line.
STREET_PARTS = {"sidewalk", "crossing", "traffic_island"}


Way = tuple[Line, object]  # (line, street key: name and type, None when unnamed)


def osm_lines(osm: OsmData) -> list[Way]:
    """Walkable OSM ways as ([[lon, lat], ...], street key), without sidewalks and crossings."""
    return [
        ([[osm.nodes[n][1], osm.nodes[n][0]] for n in nodes if n in osm.nodes], (tags["name"], tags.get("highway")) if tags.get("name") else None)
        for nodes, tags in osm.ways
        if _walkable(tags) and tags.get("footway") not in STREET_PARTS
    ]


class _Piece:
    """A stretch of an OSM way with a constant pass level."""

    def __init__(self, samples: list, passes: list[int], along: Counter, fit: float, key):
        self.samples = samples
        self.key = key
        self.passes = round(median(passes))
        self.along = along  # activity -> chunks passed along
        self.fit = fit  # mean count of activities whose GPS points fall right on the way

    def line(self) -> Line:
        s = self.samples
        return [[round(lon, 6), round(lat, 6)] for k, (_, step, lon, lat) in enumerate(s) if k in (0, len(s) - 1) or step == 0]


def _osm_pieces(ways: list[Way], wide: dict, exact: Counter, grid: Grid) -> list[_Piece]:
    """Stretches of OSM ways that activities went along, cut where the pass level changes."""
    coarse = {(x // COARSE, y // COARSE) for x, y in wide}
    coarse = widen(coarse)
    pieces = []
    for way, key in ways:
        if len(way) < 2:
            continue
        # Quick skip of the ways far from every track (most of them).
        step_deg = COARSE * CELL_M / 2
        near = False
        for (lon1, lat1), (lon2, lat2) in zip(way, way[1:]):
            n = max(1, math.ceil(math.hypot((lon2 - lon1) * grid.kx, (lat2 - lat1) * EARTH_M_PER_DEG_LAT) / step_deg))
            for t in range(n + 1):
                x, y = grid.cell_of(lon1 + t / n * (lon2 - lon1), lat1 + t / n * (lat2 - lat1))
                if (x // COARSE, y // COARSE) in coarse:
                    near = True
                    break
            if near:
                break
        if not near:
            continue
        samples = grid.samples(way)
        cells = [grid.cell_of(lon, lat) for _, _, lon, lat in samples]
        if not any(c in wide for c in cells):
            continue
        n_chunks = max(1, round(len(samples) / CHUNK))
        bounds = [round(i * len(samples) / n_chunks) for i in range(n_chunks + 1)]
        chunks = []  # (start, end, passes, along activities)
        for a, b in zip(bounds, bounds[1:]):
            hits: Counter = Counter()
            for c in cells[a:b]:
                hits.update(wide.get(c, ()))
            along = {act for act, n in hits.items() if n >= ALONG * (b - a)}
            chunks.append((a, b, len(along), along))
        # Smooth the counts over neighbouring chunks (filling a lone empty chunk), then group by level.
        raw = [c[2] for c in chunks]
        hole = [0 < i < len(raw) - 1 and not raw[i] and raw[i - 1] and raw[i + 1] for i in range(len(raw))]
        smooth = [
            min(raw[i - 1], raw[i + 1]) if hole[i] else median(raw[max(0, i - 1) : i + 2]) if raw[i] else 0
            for i in range(len(raw))
        ]
        for i in range(len(chunks)):
            if hole[i]:  # the activities that went along both sides went through it
                before, after = chunks[i - 1][3], chunks[i + 1][3]
                chunks[i] = (*chunks[i][:3], (before & after) or (before | after))
        group: list[int] = []
        for i in range(len(chunks) + 1):
            if group and (i == len(chunks) or not smooth[i] or level(smooth[i]) != level(smooth[group[0]])):
                a, b = chunks[group[0]][0], chunks[group[-1]][1]
                along = Counter(act for g in group for act in chunks[g][3])
                fit = sum(exact[c] for c in cells[a:b]) / max(b - a, 1)
                # Pieces share their end sample, so consecutive ones touch.
                pieces.append(_Piece(samples[a : min(b + 1, len(samples))], [smooth[g] for g in group], along, fit, key))
                group = []
            if i < len(chunks) and smooth[i]:
                group.append(i)
    return pieces


def frequency_collection(fc: dict, ways: list[Way] | None = None, osm_key: str = "") -> dict:
    """Each street / path once, with its count of distinct activities; busiest drawn last.

    `ways`: walkable OSM ways around the tracks (None: the tracks are drawn instead).
    Pieces carry the activity that went along them most (for the click) and, per sport,
    whether activities of that sport went there (for the sport filters).
    """
    lats = [lat for f in fc["features"] for line in f["geometry"]["coordinates"] for _, lat in line]
    grid = Grid(sum(lats) / len(lats) if lats else 45.0)
    counts: Counter = Counter()  # widened cell -> activities
    exact: Counter = Counter()  # cell -> activities whose points fall right in it
    wide: dict[tuple[int, int], list[int]] = {}  # widened cell -> activity indexes
    for i, f in enumerate(fc["features"]):
        own = {grid.cell_of(lon, lat) for line in f["geometry"]["coordinates"] for _, _, lon, lat in grid.samples(line)}
        exact.update(own)
        for c in widen(own):
            wide.setdefault(c, []).append(i)
    counts.update({c: len(acts) for c, acts in wide.items()})
    features = []

    def add(line: Line, passes: int, acts: list[int]) -> None:
        props = {"activity": fc["features"][acts[0]]["id"], "passes": passes}
        for sport in SPORTS:
            props[sport] = any(fc["features"][a]["properties"].get("sport") == sport for a in acts)
        features.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": line}, "properties": props})

    # 1. OSM ways: the best fitting way of each street draws it; ways right beside it (a sidewalk) do not.
    drawn: Drawn = {}
    for piece in sorted(_osm_pieces(ways or [], wide, exact, grid), key=lambda p: -p.fit):
        acts = [a for a, _ in piece.along.most_common()]
        parts = undrawn_parts(piece.line(), drawn, grid, key=piece.key, self_lag=None, r=1, min_run=OSM_MIN_RUN, join=OSM_JOIN)
        for part in parts:
            add(part, piece.passes, acts)

    # 2. What no OSM way explains: the tracks themselves, each path once.
    def busyness(line: Line) -> float:
        cells = [grid.cell_of(lon, lat) for _, _, lon, lat in grid.samples(line)]
        return sum(counts[c] for c in cells) / len(cells)

    # Tracks within ~30 m of a drawn way, and along it, are that way.
    near: Drawn = {}
    for (x, y), entries in drawn.items():
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                near.setdefault((x + dx, y + dy), []).extend(entries)
    drawn = near
    tracks = [(i, line) for i, f in enumerate(fc["features"]) for line in f["geometry"]["coordinates"] if len(line) >= 2]
    tracks.sort(key=lambda t: (-busyness(t[1]), -len(t[1])))
    for i, line in tracks:
        for part in undrawn_parts(line, drawn, grid):
            for passes, piece in split_by_passes(part, counts, grid):
                cells = [grid.cell_of(lon, lat) for _, _, lon, lat in grid.samples(piece)]
                # The activities that went along most of the piece (not just across it).
                hits = Counter(a for c in cells for a in wide.get(c, ()))
                acts = [i] + [a for a, n in hits.most_common() if a != i and n >= ALONG * len(cells)]
                add(piece, passes, acts)

    features.sort(key=lambda feat: feat["properties"]["passes"])  # busiest drawn last, on top
    return {
        "type": "FeatureCollection",
        "features": features,
        "max_passes": max(counts.values(), default=0),
        "levels": list(LEVELS),
        "sports": list(SPORTS),
        "signature": SIGNATURE,
        "osm": osm_key,
    }
