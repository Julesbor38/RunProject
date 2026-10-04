"""Download walkable OSM ways from Overpass, by fixed tiles cached under data/osm/."""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import httpx

# Public Overpass instances, tried in turn when one is overloaded (504/429 are common).
OVERPASS_URLS = (
    "https://overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
USER_AGENT = "trailmap/0.1 (personal running map)"
TILE_DEG = 0.05  # ~5.5 x 4 km around Lyon, ~1.5 MB of JSON in town
TILE_FORMAT_VERSION = 1
PARALLEL_DOWNLOADS = 2  # Overpass grants ~2 concurrent slots per IP

log = logging.getLogger(__name__)
_tile_locks: dict[tuple[int, int], threading.Lock] = {}
_locks_guard = threading.Lock()

# motorway/trunk are never fetched; primary is kept but heavily penalized by the cost model.
HIGHWAYS = (
    "path|footway|track|bridleway|steps|pedestrian|living_street|residential|service|"
    "unclassified|tertiary|tertiary_link|secondary|secondary_link|primary|primary_link|cycleway|road"
)


@dataclass
class OsmData:
    nodes: dict[int, tuple[float, float]]  # id -> (lat, lon)
    ways: list[tuple[list[int], dict[str, str]]]  # (node ids, tags)


def tiles_for_bbox(south: float, west: float, north: float, east: float) -> list[tuple[int, int]]:
    i0, i1 = math.floor(south / TILE_DEG), math.floor(north / TILE_DEG)
    j0, j1 = math.floor(west / TILE_DEG), math.floor(east / TILE_DEG)
    return [(i, j) for i in range(i0, i1 + 1) for j in range(j0, j1 + 1)]


def tile_path(tile: tuple[int, int], cache_dir: Path) -> Path:
    return cache_dir / f"v{TILE_FORMAT_VERSION}_{tile[0]}_{tile[1]}.json"


def download_missing(tiles: list[tuple[int, int]], cache_dir: Path) -> int:
    """Fetch uncached tiles, a few at a time. Returns the number downloaded."""
    missing = [t for t in tiles if not tile_path(t, cache_dir).exists()]
    if missing:
        with ThreadPoolExecutor(PARALLEL_DOWNLOADS) as pool:
            list(pool.map(lambda t: _tile(t, cache_dir), missing))
    return len(missing)


def load_tiles(tiles: list[tuple[int, int]], cache_dir: Path) -> OsmData:
    download_missing(tiles, cache_dir)
    nodes: dict[int, tuple[float, float]] = {}
    ways: dict[int, tuple[list[int], dict[str, str]]] = {}  # by id: ways crossing tiles appear twice
    for tile in tiles:
        data = _tile(tile, cache_dir)
        nodes.update((int(k), tuple(v)) for k, v in data["nodes"].items())
        ways.update((w["id"], (w["nodes"], w["tags"])) for w in data["ways"])
    return OsmData(nodes, list(ways.values()))


def load_cached_tiles(tiles: list[tuple[int, int]], cache_dir: Path) -> OsmData:
    """Like load_tiles, from the cache only: tiles not downloaded yet are left out."""
    return load_tiles([t for t in tiles if tile_path(t, cache_dir).exists()], cache_dir)


def _tile(tile: tuple[int, int], cache_dir: Path) -> dict:
    path = tile_path(tile, cache_dir)
    if path.exists():
        return json.loads(path.read_text())
    with _locks_guard:
        lock = _tile_locks.setdefault(tile, threading.Lock())
    with lock:  # a request and the background prefetch may want the same tile
        if path.exists():
            return json.loads(path.read_text())
        data = _download(tile)
        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(path)  # atomic: readers never see a partial file
        return data


def _download(tile: tuple[int, int]) -> dict:
    t0 = time.time()
    south, west = tile[0] * TILE_DEG, tile[1] * TILE_DEG
    bbox = f"{south:.4f},{west:.4f},{south + TILE_DEG:.4f},{west + TILE_DEG:.4f}"
    query = f'[out:json][timeout:90];way["highway"~"^({HIGHWAYS})$"]({bbox});out body;>;out skel qt;'
    raw = _fetch(query)
    data = {"nodes": {}, "ways": []}
    for e in raw["elements"]:
        if e["type"] == "node":
            data["nodes"][e["id"]] = [e["lat"], e["lon"]]
        elif e["type"] == "way":
            data["ways"].append({"id": e["id"], "nodes": e["nodes"], "tags": e.get("tags", {})})
    log.info("OSM tile %s: %d ways in %.1fs", tile, len(data["ways"]), time.time() - t0)
    return data


class OverpassError(RuntimeError):
    pass


def _fetch(query: str, rounds: int = 2) -> dict:
    errors = []
    for attempt in range(rounds):
        for url in OVERPASS_URLS:
            try:
                r = httpx.post(url, data={"data": query}, headers={"User-Agent": USER_AGENT}, timeout=90)
                r.raise_for_status()
                data = r.json()
                if "elements" in data:
                    return data
                errors.append(f"{url}: {data.get('remark', 'no elements')}")
            except (httpx.HTTPError, ValueError) as e:
                errors.append(f"{url}: {e}")
            log.warning("Overpass failed: %s", errors[-1][:200])
        time.sleep(5 * (attempt + 1))  # every instance busy: back off before another round
    raise OverpassError("serveurs OpenStreetMap (Overpass) indisponibles, réessayez dans une minute")
