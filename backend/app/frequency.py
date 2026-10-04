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
ALONG = 0.75  # an activity passed along a chunk when its widened cells hold this share of it
HIDDEN = 0.5  # a chunk this much within a parallel drawn line is a duplicate of it (a parallel path)
LINKED_M = 40  # ...unless that line is linked to it this close through the network (the same street)
GAP_M = 150  # undrawn chunks continuing a drawn street on both sides over at most this are drawn
SMOOTH_M = 150  # the shown pass count is the median along the street this far on both sides
SPUR_M = 60  # a shorter dangling chunk sticking out of a street at a junction is not drawn
LEVEL_RUN_M = 200  # along a street, a shorter stretch at another level than both sides takes theirs
CONTINUES = math.radians(35)  # chunks meeting at this angle from straight continue the same street
COARSE = 8  # coarse cells (x CELL_M) to skip quickly the ways far from any track
SPORTS = ("run", "trail_run", "hike")
VERSION = 15  # bump to invalidate the cache when the algorithm changes
# Cached results are reused only when computed with the very same settings.
SIGNATURE = (
    f"v{VERSION} cell={CELL_M} sample={SAMPLE_M} smooth={SMOOTH} levels={LEVELS}"
    f" dedup={DRAWN_CELLS},{SELF_LAG},{MIN_GAP},{MIN_RUN},{JOIN}"
    f" osm={CHUNK},{ALONG},{HIDDEN},{LINKED_M},{GAP_M},{SMOOTH_M},{SPUR_M},{LEVEL_RUN_M},{CONTINUES:.3f}"
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


# Mapped beside a street: drawing them would double the street's line (crossings are kept: they
# link a path on both sides of a road).
STREET_PARTS = {"sidewalk"}


Way = tuple[Line, object]  # (line, street key: name and type, None when unnamed)


def osm_lines(osm: OsmData) -> list[Way]:
    """Walkable OSM ways as ([[lon, lat], ...], street key), without sidewalks and crossings."""
    return [
        ([[osm.nodes[n][1], osm.nodes[n][0]] for n in nodes if n in osm.nodes], (tags["name"], tags.get("highway")) if tags.get("name") else None)
        for nodes, tags in osm.ways
        if _walkable(tags) and tags.get("footway") not in STREET_PARTS
    ]


class _Chunk:
    """A 25-50 m stretch of an OSM way, the unit that is drawn or not."""

    def __init__(self, samples: list, cells: list, key, along: set, fit: float, grid: Grid):
        self.samples = samples
        self.cells = cells
        self.key = key
        self.along = along  # activities that went along it
        self.passes = len(along)
        self.shown = 0  # pass count shown (smoothed along the street)
        self.fit = fit  # mean count of activities whose GPS points fall right on it
        self.selected = False
        self.hidden = False  # a parallel duplicate of a drawn chunk (path beside a street)
        pts = [(lon * grid.kx, lat * EARTH_M_PER_DEG_LAT) for _, _, lon, lat in samples]
        self.length = sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
        self.ends = (_point_key(samples[0]), _point_key(samples[-1]))
        # Direction leaving each end, towards the inside of the chunk.
        self.out = (_direction(pts[0], pts[min(2, len(pts) - 1)]), _direction(pts[-1], pts[max(-3, -len(pts))]))
        self.headings = [math.atan2(b[1] - a[1], b[0] - a[0]) % math.pi for a, b in zip(pts, pts[1:] + pts[-1:]) ]
        if len(pts) > 1:
            self.headings[-1] = self.headings[-2]

    def line(self) -> Line:
        s = self.samples
        return [[round(lon, 6), round(lat, 6)] for k, (_, step, lon, lat) in enumerate(s) if k in (0, len(s) - 1) or step == 0]


def _point_key(sample) -> tuple[int, int]:
    return round(sample[2] * 1e7), round(sample[3] * 1e7)


def _direction(a, b) -> float:
    return math.atan2(b[1] - a[1], b[0] - a[0])


def _split_at_junctions(ways: list[Way]) -> list[Way]:
    """Ways cut at every point they share with another way, so chunks end at junctions."""
    def k(p):
        return round(p[0] * 1e7), round(p[1] * 1e7)

    usage = Counter(k(p) for way, _ in ways for p in {tuple(q) for q in way})
    out = []
    for way, key in ways:
        start = 0
        for i in range(1, len(way) - 1):
            if usage[k(way[i])] > 1:
                out.append((way[start : i + 1], key))
                start = i
        out.append((way[start:], key))
    return out


def _osm_chunks(ways: list[Way], wide: dict, exact: Counter, grid: Grid) -> list[_Chunk]:
    """The OSM ways near tracks, cut in chunks, with the activities that went along each."""
    coarse = widen({(x // COARSE, y // COARSE) for x, y in wide})
    step_m = COARSE * CELL_M / 2
    chunks = []
    for way, key in _split_at_junctions(ways):
        if len(way) < 2:
            continue
        # Quick skip of the ways far from every track (most of them).
        near = False
        for (lon1, lat1), (lon2, lat2) in zip(way, way[1:]):
            n = max(1, math.ceil(math.hypot((lon2 - lon1) * grid.kx, (lat2 - lat1) * EARTH_M_PER_DEG_LAT) / step_m))
            if any((x // COARSE, y // COARSE) in coarse for x, y in (grid.cell_of(lon1 + t / n * (lon2 - lon1), lat1 + t / n * (lat2 - lat1)) for t in range(n + 1))):
                near = True
                break
        if not near:
            continue
        samples = grid.samples(way)
        cells = [grid.cell_of(lon, lat) for _, _, lon, lat in samples]
        n_chunks = max(1, round(len(samples) / CHUNK))
        bounds = [round(i * (len(samples) - 1) / n_chunks) for i in range(n_chunks + 1)]
        for a, b in zip(bounds, bounds[1:]):
            # Chunks share their end sample, so consecutive ones touch.
            hits: Counter = Counter()
            for c in cells[a : b + 1]:
                hits.update(wide.get(c, ()))
            along = {act for act, n in hits.items() if n >= ALONG * (b + 1 - a)}
            fit = sum(exact[c] for c in cells[a : b + 1]) / (b + 1 - a)
            chunks.append(_Chunk(samples[a : b + 1], cells[a : b + 1], key, along, fit, grid))
    return chunks


def _network(chunks: list[_Chunk]) -> dict:
    """End point -> [(chunk, end index)] of the chunks meeting there."""
    at: dict = {}
    for ch in chunks:
        for e in (0, 1):
            at.setdefault(ch.ends[e], []).append((ch, e))
    return at


def _next(ch: _Chunk, e: int, at: dict, pick) -> tuple[_Chunk, int] | None:
    """The chunk continuing `ch` straight through its end `e`, among those `pick` accepts."""
    best, best_diff = None, CONTINUES
    for other, oe in at[ch.ends[e]]:
        if other is ch or not pick(other):
            continue
        diff = abs((ch.out[e] - other.out[oe]) % (2 * math.pi) - math.pi)
        if diff < best_diff:
            best, best_diff = (other, 1 - oe), diff  # leave `other` through its far end
    return best


def _linked(ch: _Chunk, at: dict, within_m: float) -> set[int]:
    """Ids of the chunks reachable from `ch` through the network within `within_m`."""
    seen = {id(ch)}
    frontier = [(ch.ends[0], 0.0), (ch.ends[1], 0.0)]
    while frontier:
        point, dist = frontier.pop()
        for o, oe in at[point]:
            if id(o) in seen:
                continue
            seen.add(id(o))
            if dist + o.length < within_m:
                frontier.append((o.ends[1 - oe], dist + o.length))
    return seen


def _select(chunks: list[_Chunk], grid: Grid) -> None:
    """Draw each street once: chunks that activities went along, minus parallel duplicates, plus gaps."""
    at = _network(chunks)
    # 1. The best fitting streets first, as a whole (not chunk by chunk, which would make the line
    # jump between a road and the path along it); a chunk mostly within a parallel drawn line is
    # its duplicate. The chunks linked to it within LINKED_M (the same street going on, through
    # short junction bits) overlap it near the joints: they do not count, nor do short chunks.
    line_fit: dict[int, float] = {}
    for line, _ in _merged_lines(chunks, at, same_level=False, member=lambda o: o.passes > 0):
        fit = sum(c.fit * c.length for c in line) / max(sum(c.length for c in line), 1.0)
        line_fit.update((id(c), fit) for c in line)
    drawn: dict[tuple[int, int], list] = {}  # cell -> (chunk, street key, heading) drawn through it
    for ch in sorted((c for c in chunks if c.passes), key=lambda c: (-line_fit[id(c)], -c.fit)):
        if ch.length < 2 * CELL_M:
            ch.selected = True
            continue
        linked = _linked(ch, at, LINKED_M)
        hidden = sum(
            _hides([(k, h2) for o, k, h2 in drawn.get(c, ()) if id(o) not in linked], ch.key, h)
            for c, h in zip(ch.cells, ch.headings)
        )
        if hidden >= HIDDEN * len(ch.cells):
            ch.hidden = True
            continue
        ch.selected = True
        for c, h in zip(ch.cells, ch.headings):
            for n in widen([c]):
                drawn.setdefault(n, []).append((ch, ch.key, h))
    # 2. Gaps: undrawn chunks straight between drawn ones (GPS drift, a short way at a junction).
    for ch in [c for c in chunks if c.selected]:
        for e in (0, 1):
            chain, length, step = [], 0.0, _next(ch, e, at, lambda o: True)
            while step and not step[0].selected and not step[0].hidden and length + step[0].length <= GAP_M:
                chain.append(step[0])
                length += step[0].length
                step = _next(step[0], step[1], at, lambda o: True)
            if chain and step and step[0].selected:
                for g in chain:
                    g.selected = True
                    g.along = (ch.along & step[0].along) or (ch.along | step[0].along)
                    g.passes = min(ch.passes, step[0].passes)
    # 3. Short branches: from a free end to the first junction, under SPUR_M (a side street's first
    # meters, junction bits), or short pieces lying alone (a track merely brushing a way).
    def selected_at(point) -> list:
        return [(o, oe) for o, oe in at[point] if o.selected]

    for ch in chunks:
        for e in (0, 1):
            if not ch.selected or len(selected_at(ch.ends[e])) != 1:
                continue  # not a free end
            branch, length, point = [ch], ch.length, ch.ends[1 - e]
            while True:
                nxt = [(o, oe) for o, oe in selected_at(point) if o is not branch[-1]]
                if len(nxt) != 1 or length >= SPUR_M:
                    break  # a junction (or a free end) reached, or long enough to be a real line
                o, oe = nxt[0]
                branch.append(o)
                length += o.length
                point = o.ends[1 - oe]
            if length < SPUR_M:
                for b in branch:
                    b.selected = False
    # 4. Shown count: the median along the street, so the line does not flicker between levels.
    for ch in chunks:
        if not ch.selected:
            continue
        values = [(ch.passes, ch.length)]
        for e in (0, 1):
            length, step = 0.0, _next(ch, e, at, lambda o: o.selected)
            while step and length < SMOOTH_M:
                values.append((step[0].passes, step[0].length))
                length += step[0].length
                step = _next(step[0], step[1], at, lambda o: o.selected)
        values.sort()
        half, acc = sum(w for _, w in values) / 2, 0.0
        for v, w in values:
            acc += w
            if acc >= half:
                ch.shown = v
                break


def _even_levels(chunks: list[_Chunk], at: dict) -> None:
    """Along each street, short stretches at another level than their neighbours take theirs."""
    for street, _ in _merged_lines(chunks, at, same_level=False):
        for _ in range(len(street)):
            runs: list[list[_Chunk]] = []
            for c in street:
                if runs and level(runs[-1][0].shown) == level(c.shown):
                    runs[-1].append(c)
                else:
                    runs.append([c])
            if len(runs) == 1:
                break
            # The shortest stretch with a neighbour takes the level of its longer neighbour.
            length = [sum(c.length for c in r) for r in runs]
            i = min(range(len(runs)), key=lambda k: length[k])
            if length[i] >= LEVEL_RUN_M:
                break
            nb = [k for k in (i - 1, i + 1) if 0 <= k < len(runs)]
            k = max(nb, key=lambda k: length[k])
            for c in runs[i]:
                c.shown = runs[k][0].shown


def _merged_lines(chunks: list[_Chunk], at: dict, same_level: bool = True, member=None) -> list[tuple[list[_Chunk], Line]]:
    """Chunks (selected ones by default) joined into long lines where they continue each other
    straight (and, with `same_level`, at the same shown level)."""
    done: set[int] = set()
    member = member or (lambda o: o.selected)

    def same(ref: _Chunk):
        return lambda o: member(o) and id(o) not in done and (not same_level or level(o.shown) == level(ref.shown))

    out = []
    for ch in chunks:
        if not member(ch) or id(ch) in done:
            continue
        done.add(id(ch))
        # Walk back to one end of the line, then forward through it.
        back, step = [], _next(ch, 0, at, same(ch))
        while step:
            done.add(id(step[0]))
            back.append(step)
            step = _next(step[0], step[1], at, same(ch))
        forward, step = [], _next(ch, 1, at, same(ch))
        while step:
            done.add(id(step[0]))
            forward.append(step)
            step = _next(step[0], step[1], at, same(ch))
        # Orient every chunk along the line: `far` is the end the walk leaves through.
        seq = [(c, 1 - far) for c, far in reversed(back)] + [(ch, 1)] + forward
        line: Line = []
        for c, far in seq:
            pts = c.line() if far == 1 else c.line()[::-1]
            line.extend(pts if not line else pts[1:])
        out.append(([c for c, _ in seq], line))
    return out


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

    def add(line: Line, passes: int, acts: list[int], on_osm: bool) -> None:
        props = {"activity": fc["features"][acts[0]]["id"], "passes": passes, "osm": on_osm}
        for sport in SPORTS:
            props[sport] = any(fc["features"][a]["properties"].get("sport") == sport for a in acts)
        features.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": line}, "properties": props})

    # 1. OSM ways: each street once (not the path beside it), gaps closed, counts smoothed along it.
    chunks = _osm_chunks(ways or [], wide, exact, grid)
    _select(chunks, grid)
    _even_levels(chunks, _network(chunks))
    drawn: Drawn = {}
    for line_chunks, line in _merged_lines(chunks, _network(chunks)):
        along = Counter(a for c in line_chunks for a in c.along)
        shown = round(median([c.shown for c in line_chunks]))
        add(line, shown, [a for a, _ in along.most_common()] or [0], True)
        for c in line_chunks:
            for cell, h in zip(c.cells, c.headings):
                for n in widen([cell]):
                    drawn.setdefault(n, []).append((c.key, h))

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
                add(piece, passes, acts, False)

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
