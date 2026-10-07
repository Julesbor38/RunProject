"""Exploration data in SQLite (data/explore/explore.sqlite).

Per user (every row has its user, and every query asks for one user only: nothing is shown to others yet):
segments traversed (with the date and activity of their first discovery), places discovered, activities
already processed, and settings ready for leaderboards (opt-in off by default, pseudonym). Shared, public:
the communes (OSM boundaries) and their total length of walkable paths.
"""
from __future__ import annotations

import json
import math
import sqlite3
import threading
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

VERSION = 1  # of the matching: a new version re-processes the activities

SCHEMA = """
CREATE TABLE IF NOT EXISTS traversed (
  user TEXT NOT NULL, seg TEXT NOT NULL, length_m REAL NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL,
  commune TEXT, first_date TEXT, activity TEXT NOT NULL, coords TEXT NOT NULL,
  PRIMARY KEY (user, seg)
);
CREATE INDEX IF NOT EXISTS traversed_user_commune ON traversed(user, commune);
CREATE INDEX IF NOT EXISTS traversed_user_date ON traversed(user, first_date);
CREATE VIRTUAL TABLE IF NOT EXISTS traversed_rtree USING rtree(rid, min_lon, max_lon, min_lat, max_lat);
CREATE TABLE IF NOT EXISTS processed (
  user TEXT NOT NULL, activity TEXT NOT NULL, version INTEGER NOT NULL, segments INTEGER NOT NULL,
  PRIMARY KEY (user, activity)
);
CREATE TABLE IF NOT EXISTS discovered_pois (
  user TEXT NOT NULL, poi TEXT NOT NULL, name TEXT NOT NULL, category TEXT NOT NULL, kind TEXT NOT NULL,
  commune TEXT, first_date TEXT, activity TEXT NOT NULL,
  PRIMARY KEY (user, poi)
);
CREATE TABLE IF NOT EXISTS settings (
  user TEXT PRIMARY KEY,
  leaderboard_opt_in INTEGER NOT NULL DEFAULT 0,  -- future leaderboards: off unless the user turns it on
  pseudonym TEXT,                                 -- shown instead of the account name, if ever shown
  seen TEXT NOT NULL DEFAULT '[]'                 -- milestones and badges already announced
);
CREATE TABLE IF NOT EXISTS communes (
  rid INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, name TEXT NOT NULL, insee TEXT,
  polygons TEXT NOT NULL,                         -- [[outer ring, hole, …], …] of [lon, lat]
  total_m REAL                                    -- walkable paths inside, computed when first needed
);
CREATE VIRTUAL TABLE IF NOT EXISTS communes_rtree USING rtree(rid, min_lon, max_lon, min_lat, max_lat);
"""


@dataclass
class Segment:
    seg: str
    length_m: float
    lat: float
    lon: float
    commune: str | None
    first_date: str | None
    activity: str
    coords: list  # [[lon, lat], …]


@dataclass
class Commune:
    id: str
    name: str
    insee: str | None
    polygons: list
    total_m: float | None
    bbox: tuple[float, float, float, float]

    def contains(self, lat: float, lon: float) -> bool:
        return any(_in_ring(lon, lat, poly[0]) and not any(_in_ring(lon, lat, h) for h in poly[1:]) for poly in self.polygons)


class ExploreStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.executescript(SCHEMA)

    # --- activities and segments ---

    def processed(self, user: str) -> set[str]:
        with self._lock:
            rows = self._db.execute("SELECT activity FROM processed WHERE user = ? AND version = ?", (user, VERSION)).fetchall()
        return {r[0] for r in rows}

    def add_activity(self, user: str, activity: str, segments: Iterable[Segment], pois: Iterable[dict]) -> int:
        """Record an activity's segments and places (an earlier discovery keeps its date). Returns new segments."""
        new = 0
        with self._lock, self._db:
            for s in segments:
                cur = self._db.execute(
                    "INSERT OR IGNORE INTO traversed (user, seg, length_m, lat, lon, commune, first_date, activity, coords)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (user, s.seg, s.length_m, s.lat, s.lon, s.commune, s.first_date, s.activity, json.dumps(s.coords)),
                )
                if cur.rowcount:
                    new += 1
                    lons = [c[0] for c in s.coords]
                    lats = [c[1] for c in s.coords]
                    self._db.execute("INSERT INTO traversed_rtree VALUES (?,?,?,?,?)", (cur.lastrowid, min(lons), max(lons), min(lats), max(lats)))
                else:  # already known: keep the earliest discovery
                    self._db.execute(
                        "UPDATE traversed SET first_date = ?, activity = ? WHERE user = ? AND seg = ? AND first_date > ?",
                        (s.first_date, s.activity, user, s.seg, s.first_date),
                    )
            for p in pois:
                self._db.execute(
                    "INSERT INTO discovered_pois VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(user, poi) DO UPDATE SET"
                    " first_date = excluded.first_date, activity = excluded.activity WHERE excluded.first_date < discovered_pois.first_date",
                    (user, p["poi"], p["name"], p["category"], p["kind"], p.get("commune"), p["first_date"], activity),
                )
            self._db.execute("INSERT OR REPLACE INTO processed VALUES (?,?,?,?)", (user, activity, VERSION, new))
        return new

    def segments_in(self, user: str, bbox: Sequence[float], limit: int = 20000) -> list[Segment]:
        min_lon, min_lat, max_lon, max_lat = bbox
        with self._lock:
            rows = self._db.execute(
                "SELECT t.seg, t.length_m, t.lat, t.lon, t.commune, t.first_date, t.activity, t.coords FROM traversed t"
                " JOIN traversed_rtree r ON r.rid = t.rowid"
                " WHERE t.user = ? AND r.max_lon >= ? AND r.min_lon <= ? AND r.max_lat >= ? AND r.min_lat <= ? LIMIT ?",
                (user, min_lon, max_lon, min_lat, max_lat, limit),
            ).fetchall()
        return [Segment(*r[:7], json.loads(r[7])) for r in rows]

    def segment_keys(self, user: str) -> set[str]:
        with self._lock:
            return {r[0] for r in self._db.execute("SELECT seg FROM traversed WHERE user = ?", (user,))}

    def per_commune(self, user: str) -> list[dict]:
        """For each commune the user went through: km done, places discovered, last discovery."""
        with self._lock:
            rows = self._db.execute(
                "SELECT commune, sum(length_m), max(first_date) FROM traversed WHERE user = ? AND commune IS NOT NULL GROUP BY commune",
                (user,),
            ).fetchall()
            pois = dict(self._db.execute(
                "SELECT commune, count(*) FROM discovered_pois WHERE user = ? AND commune IS NOT NULL GROUP BY commune", (user,)
            ).fetchall())
            last_poi = dict(self._db.execute(
                "SELECT commune, max(first_date) FROM discovered_pois WHERE user = ? AND commune IS NOT NULL GROUP BY commune", (user,)
            ).fetchall())
        return [
            {"commune": c, "done_m": round(m), "pois": pois.get(c, 0), "last": max(filter(None, [d, last_poi.get(c)]), default=None)}
            for c, m, d in rows
        ]

    def discovered(self, user: str) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT poi, name, category, kind, commune, first_date FROM discovered_pois WHERE user = ? ORDER BY first_date", (user,)
            ).fetchall()
        return [dict(zip(("poi", "name", "category", "kind", "commune", "first_date"), r)) for r in rows]

    def totals(self, user: str) -> dict:
        with self._lock:
            m, n = self._db.execute("SELECT coalesce(sum(length_m), 0), count(*) FROM traversed WHERE user = ?", (user,)).fetchone()
            a = self._db.execute("SELECT count(*) FROM processed WHERE user = ? AND version = ?", (user, VERSION)).fetchone()[0]
        return {"done_m": round(m), "segments": n, "activities": a}

    def without_commune(self, limit: int = 50000) -> list[tuple[int, float, float, str]]:
        """(rowid, lat, lon, kind) of segments ('seg') and places ('poi') not yet placed in a commune."""
        with self._lock:
            segs = self._db.execute("SELECT rowid, lat, lon FROM traversed WHERE commune IS NULL LIMIT ?", (limit,)).fetchall()
            pois = self._db.execute("SELECT rowid, poi FROM discovered_pois WHERE commune IS NULL LIMIT ?", (limit,)).fetchall()
        return [(r, la, lo, "seg") for r, la, lo in segs] + [(r, 0.0, 0.0, f"poi:{poi}") for r, poi in pois]

    def set_commune(self, kind: str, rowid: int, commune: str) -> None:
        table = "traversed" if kind == "seg" else "discovered_pois"
        with self._lock, self._db:
            self._db.execute(f"UPDATE {table} SET commune = ? WHERE rowid = ?", (commune, rowid))

    # --- settings (leaderboards later) ---

    def settings(self, user: str) -> dict:
        with self._lock:
            row = self._db.execute("SELECT leaderboard_opt_in, pseudonym, seen FROM settings WHERE user = ?", (user,)).fetchone()
        if row is None:
            return {"leaderboard_opt_in": False, "pseudonym": None, "seen": []}
        return {"leaderboard_opt_in": bool(row[0]), "pseudonym": row[1], "seen": json.loads(row[2])}

    def mark_seen(self, user: str, ids: Iterable[str]) -> None:
        seen = sorted(set(self.settings(user)["seen"]) | set(ids))
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO settings (user, seen) VALUES (?, ?) ON CONFLICT(user) DO UPDATE SET seen = excluded.seen",
                (user, json.dumps(seen)),
            )

    # --- communes (shared) ---

    def add_communes(self, communes: Iterable[Commune]) -> int:
        n = 0
        with self._lock, self._db:
            for c in communes:
                cur = self._db.execute(
                    "INSERT OR REPLACE INTO communes (id, name, insee, polygons, total_m) VALUES (?,?,?,?,?)",
                    (c.id, c.name, c.insee, json.dumps(c.polygons), c.total_m),
                )
                self._db.execute("DELETE FROM communes_rtree WHERE rid = ?", (cur.lastrowid,))
                self._db.execute("INSERT INTO communes_rtree VALUES (?,?,?,?,?)", (cur.lastrowid, c.bbox[0], c.bbox[2], c.bbox[1], c.bbox[3]))
                n += 1
        return n

    def communes_count(self) -> int:
        with self._lock:
            return self._db.execute("SELECT count(*) FROM communes").fetchone()[0]

    def commune_at(self, lat: float, lon: float) -> Commune | None:
        for c in self._communes_where("r.max_lon >= ? AND r.min_lon <= ? AND r.max_lat >= ? AND r.min_lat <= ?", (lon, lon, lat, lat)):
            if c.contains(lat, lon):
                return c
        return None

    def commune(self, commune_id: str) -> Commune | None:
        found = self._communes_where("c.id = ?", (commune_id,))
        return found[0] if found else None

    def set_total(self, commune_id: str, total_m: float) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE communes SET total_m = ? WHERE id = ?", (total_m, commune_id))

    def _communes_where(self, where: str, args: tuple) -> list[Commune]:
        with self._lock:
            rows = self._db.execute(
                "SELECT c.id, c.name, c.insee, c.polygons, c.total_m, r.min_lon, r.min_lat, r.max_lon, r.max_lat"
                f" FROM communes c JOIN communes_rtree r ON r.rid = c.rid WHERE {where}",
                args,
            ).fetchall()
        return [Commune(r[0], r[1], r[2], json.loads(r[3]), r[4], (r[5], r[6], r[7], r[8])) for r in rows]


def _in_ring(lon: float, lat: float, ring: list) -> bool:
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        if (y1 > lat) != (y2 > lat) and lon < x1 + (lat - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def simplify_ring(ring: list[list[float]], tolerance_m: float = 15.0) -> list[list[float]]:
    """Douglas-Peucker on a [lon, lat] ring (communes are drawn and tested at ~15 m precision)."""
    if len(ring) < 5:
        return ring
    lat0 = math.radians(sum(p[1] for p in ring) / len(ring))
    k = 111_320 * math.cos(lat0)
    pts = [(p[0] * k, p[1] * 111_320) for p in ring]
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = pts[a], pts[b]
        dx, dy = bx - ax, by - ay
        norm = math.hypot(dx, dy) or 1.0
        best, at = 0.0, -1
        for i in range(a + 1, b):
            d = abs(dy * (pts[i][0] - ax) - dx * (pts[i][1] - ay)) / norm
            if d > best:
                best, at = d, i
        if best > tolerance_m:
            keep[at] = True
            stack += [(a, at), (at, b)]
    out = [p for p, k_ in zip(ring, keep) if k_]
    return out if len(out) >= 4 else ring
