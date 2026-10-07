"""Glue between the API and the router: picks OSM tiles, builds and caches graphs."""
from __future__ import annotations

import logging
import math
import threading
import time
from collections import Counter, OrderedDict
from pathlib import Path

from .elevation import Dem
from .graph import EARTH_M_PER_DEG_LAT, Graph, add_elevation, build_graph, mark_familiar
from .job import Job
from .osm import TILE_DEG, OverpassError, download_missing, load_tiles, tile_path, tiles_for_bbox
from .router import Preferences, Route, flattest, loop, loop_via, point_to_point, via_route

MAX_VIA = 3  # « Passer par ici » points per route
VIA_MAX_M = 300  # a point de passage must be that close to a path
MAX_DISTANCE_M = 60_000
GRAPH_CACHE_SIZE = 4
ENDS_DOWNLOAD_S = 180  # a generation waits this long for the tiles of its start and end, required
REQUEST_DOWNLOAD_S = 45  # then this long for the others, and routes without those still missing
RETRY_FAILED_TILE_S = 300  # a tile that just failed is not asked for again by requests before this
PREFETCH_MIN_RUNS = 2  # tiles crossed by at least this many runs are prefetched, with a 1-tile margin

log = logging.getLogger(__name__)


class RoutingError(ValueError):
    pass


class RoutingService:
    def __init__(self, osm_dir: Path, tracks: list[list[tuple[float, float]]], dem: Dem | None = None):
        self.osm_dir = osm_dir
        self.dem = dem
        self.tracks = tracks  # user's tracks as (lon, lat) polylines, for familiarity
        self._graphs: OrderedDict[tuple, Graph] = OrderedDict()
        self._failed_at: dict[tuple[int, int], float] = {}  # tile -> time its download last failed
        self._lock = threading.Lock()  # graph cache is shared by concurrent requests
        self.prefetch_tiles = home_tiles(tracks)
        self.prefetch_error: str | None = None
        self._prefetching = False
        self._requests_downloading = 0  # prefetch yields Overpass slots to user requests
        self._idle = threading.Condition()

    def start_prefetch(self) -> None:
        """Download, in the background, the OSM tiles around where the user runs."""
        if self._prefetching:
            return
        self._prefetching = True

        def run() -> None:
            failed = 0
            try:
                # Small batches so progress is visible and a request can slip its own tiles in.
                for i in range(0, len(self.prefetch_tiles), 2):
                    with self._idle:
                        self._idle.wait_for(lambda: self._requests_downloading == 0)
                    _, skipped = download_missing(self.prefetch_tiles[i : i + 2], self.osm_dir)
                    failed += len(skipped)  # they will load on demand
                if failed:
                    self.prefetch_error = f"{failed} zone(s) non téléchargée(s), elles le seront à la demande"
            finally:
                self._prefetching = False

        threading.Thread(target=run, name="osm-prefetch", daemon=True).start()

    def status(self) -> dict:
        cached = sum(tile_path(t, self.osm_dir).exists() for t in self.prefetch_tiles)
        return {
            "tiles_total": len(self.prefetch_tiles),
            "tiles_cached": cached,
            "running": self._prefetching,
            "error": self.prefetch_error,
        }

    def generate(
        self,
        start: tuple[float, float],
        prefs: Preferences,
        distance_m: float | None = None,
        end: tuple[float, float] | None = None,
        ascent_range: tuple[float, float] | None = None,
        job: Job | None = None,
        flat: bool = False,
        via: list[tuple[float, float]] | None = None,
    ) -> dict:
        """`start`/`end` are (lon, lat). A loop when `end` is None, else a point-to-point route
        (the best one, or routes of about `distance_m` when given).

        `job` reports progress and raises Cancelled once cancelled."""
        if end is None and not distance_m:
            raise RoutingError("distance requise pour une boucle")
        if distance_m and distance_m > MAX_DISTANCE_M:
            raise RoutingError(f"distance max {MAX_DISTANCE_M // 1000} km")
        job = job or Job()
        via = list(via or [])[:MAX_VIA]
        g, skipped = self._graph(start, end, distance_m, job, via)
        src = g.nearest_node(start[1], start[0])
        if src is None:
            raise RoutingError("aucun chemin à moins de 500 m du départ")
        via_nodes = []
        for lon, lat in via:
            node = g.nearest_node(lat, lon, max_m=VIA_MAX_M)
            if node is None:
                raise RoutingError(f"un point de passage est à plus de {VIA_MAX_M} m de tout chemin")
            via_nodes.append(node)
        if via_nodes and flat:
            prefs = Preferences(**{**prefs.__dict__, "hills": -1.0})
        if via_nodes and end is None:
            routes = loop_via(g, src, via_nodes, distance_m, prefs, ascent_range=None if flat else ascent_range, job=job)
        elif via_nodes:
            dst = g.nearest_node(end[1], end[0])
            if dst is None:
                raise RoutingError("aucun chemin à moins de 500 m de l'arrivée")
            routes = via_route(g, src, dst, via_nodes, prefs, distance_m, None if flat else ascent_range, job=job)
        elif end is None:
            routes = (
                flattest(g, src, distance_m, prefs, job=job)
                if flat and g.ele
                else loop(g, src, distance_m, prefs, ascent_range=ascent_range, job=job)
            )
        else:
            dst = g.nearest_node(end[1], end[0])
            if dst is None:
                raise RoutingError("aucun chemin à moins de 500 m de l'arrivée")
            routes = point_to_point(g, src, dst, prefs, distance_m, ascent_range, job=job, flat=flat and bool(g.ele))
        if not routes:
            raise RoutingError("aucun itinéraire trouvé dans cette zone")
        features = [_feature(r, g, i, ascent_range) for i, r in enumerate(routes)]
        out = {"type": "FeatureCollection", "features": features, "elevation": bool(g.ele)}
        shortest_m = min(f["properties"]["distance_m"] for f in features)
        if via_nodes and distance_m and shortest_m > 1.15 * distance_m:
            out["notice"] = f"Avec ces points de passage, l'itinéraire fait au moins {shortest_m / 1000:.1f} km.".replace(".", ",", 1)
        if skipped:
            out["warning"] = (
                f"{skipped} zone(s) OpenStreetMap n'ont pas pu être téléchargées (serveurs saturés) : "
                "les itinéraires les évitent, régénérez plus tard pour les inclure."
            )
        return out

    def _graph(self, start, end, distance_m, job: Job, via=()) -> tuple[Graph, int]:
        """Graph around the request, and the number of its tiles that could not be downloaded."""
        lons, lats = [start[0], *(v[0] for v in via)], [start[1], *(v[1] for v in via)]
        if end is not None:
            lons.append(end[0])
            lats.append(end[1])
        # Loops reach ~distance/3 from the start; a one-way detour stays within its ellipse
        # (semi-major axis ~distance/2.4) around the midpoint, so within that from either end.
        if end is None:
            margin_m = distance_m / 3 + 1000
        else:
            margin_m = max(1500, (distance_m or 0) / 2.4) + 1000
        dlat = margin_m / EARTH_M_PER_DEG_LAT
        dlon = margin_m / (111_320 * math.cos(math.radians(start[1])))
        box = tiles_for_bbox(min(lats) - dlat, min(lons) - dlon, max(lats) + dlat, max(lons) + dlon)
        a, b = (start[0], start[1]), (lons[-1], lats[-1])
        # The path start -> points de passage -> end (or back to the start): tiles near any of its legs.
        path = [a, *((v[0], v[1]) for v in via), b if end is not None else a]
        legs = list(zip(path, path[1:])) or [(a, b)]
        near = sorted((d, t) for t in box if (d := min(_tile_to_segment_m(t, p, q) for p, q in legs)) <= margin_m)
        tiles = tuple(t for _, t in near)  # nearest first: downloaded first, more useful when time runs out
        ends = list(dict.fromkeys([_tile_of(*a), _tile_of(*b), *(_tile_of(v[0], v[1]) for v in via)]))
        now = time.monotonic()
        recent = [
            t for t in tiles
            if t not in ends
            and now - self._failed_at.get(t, -math.inf) < RETRY_FAILED_TILE_S
            and not tile_path(t, self.osm_dir).exists()
        ]
        with self._lock:
            # A graph built for a wider area serves smaller requests too.
            for key, g in self._graphs.items():
                if set(tiles) - set(recent) <= set(key):
                    self._graphs.move_to_end(key)
                    return g, len(recent)
        with self._idle:
            self._requests_downloading += 1
        try:
            # The ends' tiles are required; one far from them that fails only narrows the choice of routes.
            _, failed = download_missing(ends, self.osm_dir, job, ENDS_DOWNLOAD_S, stage="download_ends")
            if failed:
                raise RoutingError(
                    "les serveurs OpenStreetMap (Overpass) sont saturés et les chemins autour du "
                    f"{'départ' if _tile_of(*a) in failed else 'point d\'arrivée'} ne sont pas encore connus : "
                    "le téléchargement continue en arrière-plan, réessayez dans quelques minutes"
                )
            rest = [t for t in tiles if t not in recent and t not in ends]
            _, failed = download_missing(rest, self.osm_dir, job, REQUEST_DOWNLOAD_S)
        finally:
            with self._idle:
                self._requests_downloading -= 1
                self._idle.notify_all()
        self._failed_at.update(dict.fromkeys(failed, time.monotonic()))
        failed += recent
        tiles = tuple(t for t in tiles if t not in failed)
        job.step("graph")
        try:
            osm = load_tiles(list(tiles), self.osm_dir)
        except OverpassError as e:
            raise RoutingError(str(e)) from e
        g = build_graph(osm)
        job.check()
        mark_familiar(g, self.tracks)
        job.check()
        if self.dem is not None:
            try:
                add_elevation(g, self.dem)
            except Exception as e:  # noqa: BLE001 - routing still works without elevation
                log.warning("elevation unavailable: %s", e)
        with self._lock:
            self._graphs[tiles] = g  # without the failed tiles: a later request retries them
            if len(self._graphs) > GRAPH_CACHE_SIZE:
                self._graphs.popitem(last=False)
        return g, len(failed)


def _tile_of(lon: float, lat: float) -> tuple[int, int]:
    return math.floor(lat / TILE_DEG), math.floor(lon / TILE_DEG)


def _tile_to_segment_m(tile: tuple[int, int], a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distance (m) from a tile to the segment between the (lon, lat) points a and b.

    Routes stay within a band around the start-end segment (a disc around the start for
    loops): the box's corner tiles beyond it need not be downloaded.
    """
    ky = EARTH_M_PER_DEG_LAT
    kx = 111_320 * math.cos(math.radians(a[1]))
    south, west = tile[0] * TILE_DEG, tile[1] * TILE_DEG
    x0, x1, y0, y1 = west * kx, (west + TILE_DEG) * kx, south * ky, (south + TILE_DEG) * ky
    (ax, ay), (bx, by) = (a[0] * kx, a[1] * ky), (b[0] * kx, b[1] * ky)
    n = max(1, math.ceil(math.hypot(bx - ax, by - ay) / 100))  # samples every 100 m along the segment
    best = math.inf
    for i in range(n + 1):
        x, y = ax + (bx - ax) * i / n, ay + (by - ay) * i / n
        best = min(best, math.hypot(max(x0 - x, 0, x - x1), max(y0 - y, 0, y - y1)))
    return best - 50  # half a sample step


def home_tiles(tracks: list[list[tuple[float, float]]]) -> list[tuple[int, int]]:
    """Tiles to prefetch: crossed by at least PREFETCH_MIN_RUNS tracks plus their neighbours (routing
    around home), busiest first, then every other tile a track crossed."""
    runs: Counter[tuple[int, int]] = Counter()
    for line in tracks:
        runs.update({(math.floor(lat / TILE_DEG), math.floor(lon / TILE_DEG)) for lon, lat in line})
    core = [t for t, n in runs.most_common() if n >= PREFETCH_MIN_RUNS]
    out: dict[tuple[int, int], None] = dict.fromkeys(core)
    for i, j in core:
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                out.setdefault((i + di, j + dj))
    for t, _ in runs.most_common():
        out.setdefault(t)
    return list(out)


def _feature(r: Route, g: Graph, i: int, ascent_range: tuple[float, float] | None) -> dict:
    props = r.stats(g)
    if ascent_range is not None and g.ele:
        props["in_ascent_range"] = ascent_range[0] <= props["ascent_m"] <= ascent_range[1]
    return {
        "type": "Feature",
        "id": i,
        "geometry": {"type": "LineString", "coordinates": r.coords3d(g)},
        "properties": props,
    }
