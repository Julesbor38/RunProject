"""Communes (OSM boundary=administrative, admin_level=8) and the walkable paths they hold.

Boundaries are extracted once from the France extract:
    python -m app.explore.communes ../data/osm/france-latest.osm.pbf [--force]
The total length of walkable paths of a commune (the router's paths, from the cached tiles) is computed the
first time a user goes through it, then kept.
"""
from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from ..routing.graph import Graph, build_graph
from ..routing.osm import load_cached_tiles, tile_path, tiles_for_bbox
from .matching import edge_midpoint, explorable
from .store import Commune, ExploreStore, simplify_ring

LOCATIONS_IN_MEMORY_MAX_PBF = 1_500_000_000
log = logging.getLogger(__name__)


def extract(pbf: Path, store: ExploreStore) -> int:
    import osmium

    work = store.path.parent / "communes.tmp"
    work.mkdir(parents=True, exist_ok=True)
    index = "sparse_mem_array" if pbf.stat().st_size <= LOCATIONS_IN_MEMORY_MAX_PBF else f"sparse_file_array,{work / 'locations.idx'}"
    processor = (
        osmium.FileProcessor(str(pbf))
        .with_locations(index)
        .with_areas(osmium.filter.TagFilter(("boundary", "administrative")))
        .with_filter(osmium.filter.TagFilter(("admin_level", "8")))
    )
    batch: list[Commune] = []
    total = 0
    t0 = time.time()
    for obj in processor:
        if not obj.is_area() or obj.tags.get("boundary") != "administrative" or not obj.tags.get("name"):
            continue
        polygons = []
        for outer in obj.outer_rings():
            rings = [[[n.lon, n.lat] for n in outer if n.location.valid()]]
            rings += [[[n.lon, n.lat] for n in inner if n.location.valid()] for inner in obj.inner_rings(outer)]
            rings = [simplify_ring(r) for r in rings if len(r) >= 4]
            if rings:
                polygons.append(rings)
        if not polygons:
            continue
        pts = [p for poly in polygons for p in poly[0]]
        insee = obj.tags.get("ref:INSEE")
        batch.append(Commune(
            insee or f"{'w' if obj.from_way() else 'r'}{obj.orig_id()}", obj.tags["name"], insee, polygons, None,
            (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)),
        ))
        if len(batch) >= 2000:
            total += store.add_communes(batch)
            batch.clear()
            log.info("%d communes (%.0fs)", total, time.time() - t0)
    total += store.add_communes(batch)
    log.info("%d communes in %.0fs", total, time.time() - t0)
    for f in work.glob("*"):
        f.unlink()
    work.rmdir()
    return total


def walkable_total(commune: Commune, osm_dir: Path, graph: Graph | None = None) -> float | None:
    """Length (m) of the router's walkable paths whose middle lies in the commune; None if tiles are missing."""
    min_lon, min_lat, max_lon, max_lat = commune.bbox
    tiles = tiles_for_bbox(min_lat, min_lon, max_lat, max_lon)
    if graph is None:
        if not all(tile_path(t, osm_dir).exists() for t in tiles):
            return None
        graph = build_graph(load_cached_tiles(tiles, osm_dir))
    total = 0.0
    for e in graph.edges:
        if not explorable(e):
            continue
        lat, lon = edge_midpoint(graph, e)
        if min_lon <= lon <= max_lon and min_lat <= lat <= max_lat and commune.contains(lat, lon):
            total += e.length_m
    return round(total)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pbf", type=Path)
    parser.add_argument("--db", type=Path, default=Path(__file__).parents[3] / "data" / "explore" / "explore.sqlite")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print(extract(args.pbf, ExploreStore(args.db)), "communes")


if __name__ == "__main__":
    main()
