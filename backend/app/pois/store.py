"""Notable places in SQLite (data/pois/pois.sqlite): an R-tree for the visible area, and the caches of
Wikidata answers and of the Overpass zones fetched outside France. Shared by all accounts (public OSM data).
"""
from __future__ import annotations

import json
import math
import sqlite3
import threading
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

EARTH_M_PER_DEG = 111_320.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS pois (
  rid INTEGER PRIMARY KEY,
  id TEXT UNIQUE NOT NULL,       -- n123 / w123 / r123 (OSM), or the river's name cell
  lat REAL NOT NULL, lon REAL NOT NULL,
  category TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL,
  score REAL NOT NULL, min_zoom INTEGER NOT NULL,
  radius_m REAL NOT NULL DEFAULT 0, -- surfaces: radius of a disc of the same area
  tags TEXT NOT NULL,
  source TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS pois_rtree USING rtree(rid, min_lon, max_lon, min_lat, max_lat);
CREATE INDEX IF NOT EXISTS pois_source ON pois(source);
CREATE TABLE IF NOT EXISTS wikidata (qid TEXT PRIMARY KEY, data TEXT NOT NULL, fetched REAL NOT NULL);
CREATE TABLE IF NOT EXISTS overpass_zones (zone TEXT PRIMARY KEY, fetched REAL NOT NULL, ok INTEGER NOT NULL);
"""


@dataclass
class Poi:
    id: str
    lat: float
    lon: float
    category: str
    kind: str
    name: str
    score: float
    min_zoom: int
    tags: dict = field(default_factory=dict)
    radius_m: float = 0.0
    source: str = "france"

    def feature(self) -> dict:
        return {
            "type": "Feature",
            "id": self.id,
            "geometry": {"type": "Point", "coordinates": [round(self.lon, 6), round(self.lat, 6)]},
            "properties": {"id": self.id, "category": self.category, "kind": self.kind, "name": self.name, "score": self.score},
        }


class PoiStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        self._db.close()

    # --- writing ---

    def add(self, pois: Iterable[Poi]) -> int:
        """Insert places (an existing id is kept: same OSM object). Returns how many were new."""
        added = 0
        with self._lock, self._db:
            for p in pois:
                cur = self._db.execute(
                    "INSERT OR IGNORE INTO pois (id, lat, lon, category, kind, name, score, min_zoom, radius_m, tags, source)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (p.id, p.lat, p.lon, p.category, p.kind, p.name, p.score, p.min_zoom, p.radius_m, json.dumps(p.tags, ensure_ascii=False), p.source),
                )
                if cur.rowcount:
                    self._db.execute("INSERT INTO pois_rtree VALUES (?,?,?,?,?)", (cur.lastrowid, p.lon, p.lon, p.lat, p.lat))
                    added += 1
        return added

    def clear_source(self, source: str) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM pois_rtree WHERE rid IN (SELECT rid FROM pois WHERE source = ?)", (source,))
            self._db.execute("DELETE FROM pois WHERE source = ?", (source,))

    # --- reading ---

    def in_bbox(
        self, bbox: Sequence[float], zoom: float | None = None, categories: Iterable[str] | None = None, limit: int = 400
    ) -> list[Poi]:
        """Best places in (min_lon, min_lat, max_lon, max_lat), shown at that zoom, of those categories."""
        min_lon, min_lat, max_lon, max_lat = bbox
        sql = (
            "SELECT p.* FROM pois p JOIN pois_rtree r ON r.rid = p.rid"
            " WHERE r.max_lon >= ? AND r.min_lon <= ? AND r.max_lat >= ? AND r.min_lat <= ?"
        )
        args: list = [min_lon, max_lon, min_lat, max_lat]
        if zoom is not None:
            sql += " AND p.min_zoom <= ?"
            args.append(zoom)
        cats = list(categories) if categories is not None else None
        if cats is not None:
            if not cats:
                return []
            sql += f" AND p.category IN ({','.join('?' * len(cats))})"
            args += cats
        sql += " ORDER BY p.score DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self._db.execute(sql, args).fetchall()
        return [_poi(r) for r in rows]

    def get(self, poi_id: str) -> Poi | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM pois WHERE id = ?", (poi_id,)).fetchone()
        return _poi(row) if row else None

    def count(self) -> int:
        with self._lock:
            return self._db.execute("SELECT count(*) FROM pois").fetchone()[0]

    def along(self, line: Sequence[Sequence[float]], within_m: float = 50.0, limit: int = 30) -> list[Poi]:
        """Places within `within_m` of a [lon, lat] polyline (surfaces: of their edge, roughly), best first."""
        if len(line) < 2:
            return []
        lons = [c[0] for c in line]
        lats = [c[1] for c in line]
        lat0 = math.radians(sum(lats) / len(lats))
        pad = (within_m + 500) / EARTH_M_PER_DEG  # surfaces reach further than their point
        found = self.in_bbox((min(lons) - pad / math.cos(lat0), min(lats) - pad, max(lons) + pad / math.cos(lat0), max(lats) + pad), limit=5000)
        k = EARTH_M_PER_DEG * math.cos(lat0)
        pts = [(c[0] * k, c[1] * EARTH_M_PER_DEG) for c in line]
        out = []
        for p in found:
            reach = within_m + min(p.radius_m, 500.0)
            if _dist_to_line((p.lon * k, p.lat * EARTH_M_PER_DEG), pts) <= reach:
                out.append(p)
        return sorted(out, key=lambda p: -p.score)[:limit]

    # --- caches ---

    def wikidata_get(self, qid: str) -> tuple[dict, float] | None:
        with self._lock:
            row = self._db.execute("SELECT data, fetched FROM wikidata WHERE qid = ?", (qid,)).fetchone()
        return (json.loads(row[0]), row[1]) if row else None

    def wikidata_put(self, qid: str, data: dict, fetched: float) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO wikidata VALUES (?,?,?)", (qid, json.dumps(data, ensure_ascii=False), fetched))

    def zone_state(self, zone: str) -> tuple[float, bool] | None:
        with self._lock:
            row = self._db.execute("SELECT fetched, ok FROM overpass_zones WHERE zone = ?", (zone,)).fetchone()
        return (row[0], bool(row[1])) if row else None

    def zone_put(self, zone: str, fetched: float, ok: bool) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT OR REPLACE INTO overpass_zones VALUES (?,?,?)", (zone, fetched, int(ok)))


def _poi(row: tuple) -> Poi:
    _, id_, lat, lon, cat, kind, name, score, mz, radius, tags, source = row
    return Poi(id_, lat, lon, cat, kind, name, score, mz, json.loads(tags), radius, source)


def _dist_to_line(p: tuple[float, float], pts: list[tuple[float, float]]) -> float:
    best = math.inf
    px, py = p
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        dx, dy = bx - ax, by - ay
        seg = dx * dx + dy * dy
        t = 0.0 if seg == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg))
        best = min(best, math.hypot(px - (ax + t * dx), py - (ay + t * dy)))
    return best
