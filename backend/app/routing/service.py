"""Glue between the API and the router: picks OSM tiles, builds and caches graphs."""
from __future__ import annotations

import logging
import math
import threading
from collections import Counter, OrderedDict
from pathlib import Path

from .elevation import Dem
from .graph import EARTH_M_PER_DEG_LAT, Graph, add_elevation, build_graph, mark_familiar
from .osm import TILE_DEG, OverpassError, download_missing, load_tiles, tile_path, tiles_for_bbox
from .router import Preferences, Route, loop, point_to_point

MAX_DISTANCE_M = 60_000
GRAPH_CACHE_SIZE = 4
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
                    try:
                        download_missing(self.prefetch_tiles[i : i + 2], self.osm_dir)
                    except Exception as e:  # noqa: BLE001 - skip the tile, it will load on demand
                        failed += 1
                        log.warning("OSM prefetch: tiles skipped: %s", e)
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
    ) -> dict:
        """`start`/`end` are (lon, lat). A loop when `end` is None, else a point-to-point route."""
        if end is None and not distance_m:
            raise RoutingError("distance requise pour une boucle")
        if distance_m and distance_m > MAX_DISTANCE_M:
            raise RoutingError(f"distance max {MAX_DISTANCE_M // 1000} km")
        g = self._graph(start, end, distance_m)
        src = g.nearest_node(start[1], start[0])
        if src is None:
            raise RoutingError("aucun chemin à moins de 500 m du départ")
        if end is None:
            routes = loop(g, src, distance_m, prefs, ascent_range=ascent_range)
        else:
            dst = g.nearest_node(end[1], end[0])
            if dst is None:
                raise RoutingError("aucun chemin à moins de 500 m de l'arrivée")
            routes = point_to_point(g, src, dst, prefs)
        if not routes:
            raise RoutingError("aucun itinéraire trouvé dans cette zone")
        features = [_feature(r, g, i, ascent_range) for i, r in enumerate(routes)]
        return {"type": "FeatureCollection", "features": features, "elevation": bool(g.ele)}

    def _graph(self, start, end, distance_m) -> Graph:
        lons, lats = [start[0]], [start[1]]
        if end is not None:
            lons.append(end[0])
            lats.append(end[1])
        margin_m = (distance_m / 3 if end is None else 1500) + 1000
        dlat = margin_m / EARTH_M_PER_DEG_LAT
        dlon = margin_m / (111_320 * math.cos(math.radians(start[1])))
        tiles = tuple(tiles_for_bbox(min(lats) - dlat, min(lons) - dlon, max(lats) + dlat, max(lons) + dlon))
        with self._lock:
            # A graph built for a wider area serves smaller requests too.
            for key, g in self._graphs.items():
                if set(tiles) <= set(key):
                    self._graphs.move_to_end(key)
                    return g
        with self._idle:
            self._requests_downloading += 1
        try:
            osm = load_tiles(list(tiles), self.osm_dir)
        except OverpassError as e:
            raise RoutingError(str(e)) from e
        finally:
            with self._idle:
                self._requests_downloading -= 1
                self._idle.notify_all()
        g = build_graph(osm)
        mark_familiar(g, self.tracks)
        if self.dem is not None:
            try:
                add_elevation(g, self.dem)
            except Exception as e:  # noqa: BLE001 - routing still works without elevation
                log.warning("elevation unavailable: %s", e)
        with self._lock:
            self._graphs[tiles] = g
            if len(self._graphs) > GRAPH_CACHE_SIZE:
                self._graphs.popitem(last=False)
        return g


def home_tiles(tracks: list[list[tuple[float, float]]]) -> list[tuple[int, int]]:
    """Tiles crossed by at least PREFETCH_MIN_RUNS tracks, plus their neighbours, busiest first."""
    runs: Counter[tuple[int, int]] = Counter()
    for line in tracks:
        runs.update({(math.floor(lat / TILE_DEG), math.floor(lon / TILE_DEG)) for lon, lat in line})
    core = [t for t, n in runs.most_common() if n >= PREFETCH_MIN_RUNS]
    out: dict[tuple[int, int], None] = dict.fromkeys(core)
    for i, j in core:
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                out.setdefault((i + di, j + dj))
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
