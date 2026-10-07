"""Notable places from an OSM extract (.osm.pbf, e.g. data/osm/france-latest.osm.pbf) into the place store.

Nodes are places as they are; surfaces (parks, lakes, reserves: closed ways and multipolygons) become their
centre, with their size; named rivers and streams one point per name and ~5 km cell; other lines (city walls,
aqueducts) their middle node. The same place drawn twice (node + surface) is kept once.

Run: python -m app.pois.extract ../data/osm/france-latest.osm.pbf [--force]   (~30-60 min for France)
"""
from __future__ import annotations

import argparse
import logging
import math
import shutil
import time
from pathlib import Path

from .catalog import classify, kept, min_zoom, name_of, score
from .store import EARTH_M_PER_DEG, Poi, PoiStore

KEYS = ("tourism", "natural", "leisure", "boundary", "waterway", "historic", "heritage", "ref:mhs", "amenity")
LOCATIONS_IN_MEMORY_MAX_PBF = 1_500_000_000  # like the routing extract: bigger ones index node locations on disk
RIVER_CELL_DEG = 0.05
DUPLICATE_M = 150.0
BATCH = 20_000

log = logging.getLogger(__name__)


def extract(pbf: Path, store: PoiStore, source: str = "france", force: bool = False) -> int:
    """Add the extract's places to the store (replacing that source's with `force`). Returns how many."""
    import osmium  # only needed here

    if force:
        store.clear_source(source)
    work = store.path.parent / "extract.tmp"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    index = "sparse_mem_array" if pbf.stat().st_size <= LOCATIONS_IN_MEMORY_MAX_PBF else f"sparse_file_array,{work / 'locations.idx'}"
    processor = (
        osmium.FileProcessor(str(pbf))
        .with_locations(index)
        .with_areas(osmium.filter.KeyFilter(*KEYS))
        .with_filter(osmium.filter.KeyFilter(*KEYS))
    )
    batch: list[Poi] = []
    rivers: dict[tuple[str, int, int], Poi] = {}
    total = 0
    t0 = time.time()

    def flush() -> None:
        nonlocal total
        total += store.add(batch)
        batch.clear()

    for obj in processor:
        tags = {t.k: t.v for t in obj.tags}
        found = classify(tags)
        if found is None:
            continue
        category, kind = found
        if obj.is_node():
            if obj.location.valid():
                batch.append(_poi(f"n{obj.id}", obj.location.lat, obj.location.lon, category, kind, tags, 0.0, source))
        elif obj.is_area():
            point = _area_centre(obj)
            if point is not None:
                lat, lon, area = point
                prefix = "w" if obj.from_way() else "r"
                batch.append(_poi(f"{prefix}{obj.orig_id()}", lat, lon, category, kind, tags, area, source))
        elif obj.is_way():
            locs = [n.location for n in obj.nodes if n.location.valid()]
            if not locs or (obj.is_closed() and kind not in ("river", "stream")):
                continue  # closed ways come again as surfaces
            mid = locs[len(locs) // 2]
            if kind in ("river", "stream"):
                key = (name_of(tags), math.floor(mid.lat / RIVER_CELL_DEG), math.floor(mid.lon / RIVER_CELL_DEG))
                rivers.setdefault(key, _poi(f"w{obj.id}", mid.lat, mid.lon, category, kind, tags, 0.0, source))
            else:
                batch.append(_poi(f"w{obj.id}", mid.lat, mid.lon, category, kind, tags, 0.0, source))
        if len(batch) >= BATCH:
            flush()
            log.info("%d places (%.0fs)", total, time.time() - t0)
    batch.extend(rivers.values())
    flush()
    removed = remove_duplicates(store, source)
    shutil.rmtree(work, ignore_errors=True)
    log.info("%d places, %d duplicates removed, in %.0fs", total - removed, removed, time.time() - t0)
    return total - removed


def _poi(id_: str, lat: float, lon: float, category: str, kind: str, tags: dict, area_m2: float, source: str) -> Poi:
    s = score(tags, kind, area_m2)
    radius = math.sqrt(area_m2 / math.pi) if area_m2 else 0.0
    return Poi(id_, lat, lon, category, kind, name_of(tags), s, min_zoom(s), kept(tags), round(radius), source)


def _area_centre(area) -> tuple[float, float, float] | None:
    """(lat, lon, m²): centre of the largest outer ring, total outer area."""
    best: tuple[float, float, float] | None = None
    total = 0.0
    for ring in area.outer_rings():
        pts = [(n.lon, n.lat) for n in ring if n.location.valid()]
        if len(pts) < 3:
            continue
        c = _ring_centre(pts)
        if c is None:
            continue
        lat, lon, a = c
        total += a
        if best is None or a > best[2]:
            best = (lat, lon, a)
    return (best[0], best[1], total) if best else None


def _ring_centre(pts: list[tuple[float, float]]) -> tuple[float, float, float] | None:
    """Centroid (lat, lon) and area (m²) of a ring of (lon, lat), in a local plane."""
    lat0 = math.radians(sum(p[1] for p in pts) / len(pts))
    kx, ky = EARTH_M_PER_DEG * math.cos(lat0), EARTH_M_PER_DEG
    xs = [p[0] * kx for p in pts]
    ys = [p[1] * ky for p in pts]
    a = cx = cy = 0.0
    for i in range(len(pts)):
        j = (i + 1) % len(pts)
        cross = xs[i] * ys[j] - xs[j] * ys[i]
        a += cross
        cx += (xs[i] + xs[j]) * cross
        cy += (ys[i] + ys[j]) * cross
    if abs(a) < 1e-6:
        return None
    a /= 2
    return cy / (6 * a) / ky, cx / (6 * a) / kx, abs(a)


def remove_duplicates(store: PoiStore, source: str) -> int:
    """The same named place drawn as a node and a surface (or twice): keep the best within DUPLICATE_M."""
    db = store._db
    with store._lock:
        groups = db.execute(
            "SELECT category, lower(name) FROM pois WHERE source = ? AND name != '' GROUP BY category, lower(name) HAVING count(*) > 1",
            (source,),
        ).fetchall()
    drop: list[int] = []
    for category, name in groups:
        with store._lock:
            rows = db.execute(
                "SELECT rid, lat, lon, score FROM pois WHERE source = ? AND category = ? AND lower(name) = ? ORDER BY score DESC, id",
                (source, category, name),
            ).fetchall()
        kept_rows: list[tuple[float, float]] = []
        for rid, lat, lon, _ in rows:
            k = EARTH_M_PER_DEG * math.cos(math.radians(lat))
            if any(math.hypot((lon - lo) * k, (lat - la) * EARTH_M_PER_DEG) < DUPLICATE_M for la, lo in kept_rows):
                drop.append(rid)
            else:
                kept_rows.append((lat, lon))
    with store._lock, db:
        for i in range(0, len(drop), 500):
            part = drop[i : i + 500]
            marks = ",".join("?" * len(part))
            db.execute(f"DELETE FROM pois_rtree WHERE rid IN ({marks})", part)
            db.execute(f"DELETE FROM pois WHERE rid IN ({marks})", part)
    return len(drop)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pbf", type=Path)
    parser.add_argument("--db", type=Path, default=Path(__file__).parents[3] / "data" / "pois" / "pois.sqlite")
    parser.add_argument("--source", default="france")
    parser.add_argument("--force", action="store_true", help="replace the places already extracted from this source")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    store = PoiStore(args.db)
    print(extract(args.pbf, store, args.source, args.force), "places")


if __name__ == "__main__":
    main()
