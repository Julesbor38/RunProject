"""Cut a regional OSM extract (.osm.pbf, e.g. from Geofabrik) into the tiles otherwise fetched
from Overpass, so routing in that region needs no Overpass at all.

Tiles are written in the Overpass tile format, only where they lie wholly inside the region's
boundary (.poly): border tiles would miss the ways beyond it and keep coming from Overpass.

Run: python -m app.routing.extract data/osm/france-latest.osm.pbf data/osm/france.poly [--force]
(--force rewrites tiles already cached, to refresh them from a newer extract).
Node locations are kept in memory for a regional extract, on disk for a whole country (about
16 bytes per node: France is over 10 GB).
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import re
import shutil
import time
from collections import defaultdict
from pathlib import Path

from .osm import HIGHWAYS, TILE_DEG, tile_path, tiles_for_bbox

FLUSH_LINES = 300_000  # ways buffered in memory before they are appended to the per-tile files
LOCATIONS_IN_MEMORY_MAX_PBF = 1_500_000_000  # bigger extracts index node locations in a file instead

log = logging.getLogger(__name__)
Ring = list[tuple[float, float]]  # (lon, lat)


def read_poly(path: Path) -> tuple[list[Ring], list[Ring]]:
    """Outer rings and holes of an Osmosis .poly file."""
    outer: list[Ring] = []
    holes: list[Ring] = []
    lines = [l.strip() for l in path.read_text().splitlines()]
    i = 1  # first line: the polygon's name
    while i < len(lines) and lines[i] != "END":
        hole = lines[i].startswith("!")
        ring: Ring = []
        i += 1
        while lines[i] != "END":
            lon, lat = (float(v) for v in lines[i].split())
            ring.append((lon, lat))
            i += 1
        (holes if hole else outer).append(ring)
        i += 1
    return outer, holes


def _in_ring(lon: float, lat: float, ring: Ring) -> bool:
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def inside_tiles(outer: list[Ring], holes: list[Ring]) -> set[tuple[int, int]]:
    """Tiles whose corners and center are all inside the region."""

    def inside(lon: float, lat: float) -> bool:
        return any(_in_ring(lon, lat, r) for r in outer) and not any(_in_ring(lon, lat, r) for r in holes)

    pts = [p for r in outer for p in r]
    box = tiles_for_bbox(min(p[1] for p in pts), min(p[0] for p in pts), max(p[1] for p in pts), max(p[0] for p in pts))
    out = set()
    for i, j in box:
        s, w = i * TILE_DEG, j * TILE_DEG
        probes = [(w, s), (w + TILE_DEG, s), (w, s + TILE_DEG), (w + TILE_DEG, s + TILE_DEG), (w + TILE_DEG / 2, s + TILE_DEG / 2)]
        if all(inside(lon, lat) for lon, lat in probes):
            out.add((i, j))
    return out


def extract(pbf: Path, poly: Path, cache_dir: Path, force: bool = False) -> int:
    """Write the region's tiles into `cache_dir`. Returns the number of tiles written."""
    import osmium  # only needed here: the API does not depend on it

    region = inside_tiles(*read_poly(poly))
    todo = {t for t in region if force or not tile_path(t, cache_dir).exists()}
    log.info("%d tiles inside the region, %d to write", len(region), len(todo))
    if not todo:
        return 0
    work = cache_dir / "extract.tmp"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    wanted = re.compile(f"^({HIGHWAYS})$")
    buffer: dict[tuple[int, int], list[str]] = defaultdict(list)
    buffered = ways = 0
    t0 = time.time()

    def flush() -> None:
        for (i, j), lines in buffer.items():
            with open(work / f"{i}_{j}.jsonl", "a") as f:
                f.write("".join(lines))
        buffer.clear()

    index = "sparse_mem_array" if pbf.stat().st_size <= LOCATIONS_IN_MEMORY_MAX_PBF else f"sparse_file_array,{work / 'locations.idx'}"
    log.info("node locations: %s", index.split(",")[0])
    processor = osmium.FileProcessor(str(pbf)).with_locations(index).with_filter(osmium.filter.KeyFilter("highway"))
    for obj in processor:
        if not obj.is_way() or not wanted.match(obj.tags.get("highway", "")):
            continue
        refs, coords = [], []
        for n in obj.nodes:
            if n.location.valid():
                refs.append(n.ref)
                coords.append([round(n.lat, 7), round(n.lon, 7)])
        if len(refs) < 2:
            continue
        # Like Overpass, a tile gets every way with a node in it, with all of that way's nodes.
        tiles = {(math.floor(lat / TILE_DEG), math.floor(lon / TILE_DEG)) for lat, lon in coords} & todo
        if not tiles:
            continue
        line = json.dumps({"id": obj.id, "nodes": refs, "coords": coords, "tags": dict(obj.tags)}) + "\n"
        for t in tiles:
            buffer[t].append(line)
        buffered += len(tiles)
        ways += 1
        if buffered >= FLUSH_LINES:
            flush()
            buffered = 0
            log.info("%d ways read (%.0fs)", ways, time.time() - t0)
    flush()

    for t in todo:
        data: dict = {"nodes": {}, "ways": []}
        part = work / f"{t[0]}_{t[1]}.jsonl"
        if part.exists():
            with open(part) as f:
                for line in f:
                    w = json.loads(line)
                    data["nodes"].update(zip(map(str, w["nodes"]), w["coords"]))
                    data["ways"].append({"id": w["id"], "nodes": w["nodes"], "tags": w["tags"]})
        path = tile_path(t, cache_dir)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(path)  # atomic: a running API never reads a partial tile
    shutil.rmtree(work)
    log.info("%d tiles written, %d ways, in %.0fs", len(todo), ways, time.time() - t0)
    return len(todo)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pbf", type=Path)
    parser.add_argument("poly", type=Path)
    parser.add_argument("--cache-dir", type=Path, default=Path(__file__).parents[3] / "data" / "osm")
    parser.add_argument("--force", action="store_true", help="rewrite tiles already cached")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    extract(args.pbf, args.poly, args.cache_dir, args.force)


if __name__ == "__main__":
    main()
