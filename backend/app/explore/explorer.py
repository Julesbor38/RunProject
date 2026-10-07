"""Exploration of one user: their activities matched onto the OSM paths, the area discovered around them
(50 m each side), per commune progress (paths and area), places
discovered, milestones and badges, suggestions of unexplored paths nearby. Run in the background, only for
the activities not processed yet (a new import only costs its new activities)."""
from __future__ import annotations

import logging
import math
import threading
from collections import Counter, OrderedDict
from collections.abc import Callable, Iterable
from pathlib import Path

import numpy as np

from ..ingest import load_zones, mask
from ..ingest.models import Activity
from ..ingest.pipeline import ingest
from ..ingest.privacy import DEFAULT_TRIM_M
from ..routing.graph import EARTH_M_PER_DEG_LAT, Graph, build_graph
from ..routing.osm import TILE_DEG, load_cached_tiles, tile_path
from .area import cell_area, cell_center, corridor_cells, in_polygons, polygons_area
from .communes import walkable_total
from .matching import EdgeIndex, edge_midpoint, explorable, moving_parts, segment_key, traversed_edges
from .store import ExploreStore, Segment

POI_DISCOVERY_M = 30.0
TIMED_SHARE = 0.8  # an activity counts when this share of its points has a time (a recorded one, not a plan)
REGION_DEG = 0.15  # graphs are built for aligned regions, shared by nearby activities
MILESTONES = (10, 25, 50, 75, 90)
SUGGEST_RADIUS_M = 8000
SUGGEST_CELL_M = 1000

log = logging.getLogger(__name__)


class Explorer:
    def __init__(self, store: ExploreStore, osm_dir: Path, pois=None):
        self.store = store
        self.osm_dir = osm_dir
        self.pois = pois  # PoiStore | None
        self._graphs: OrderedDict[tuple, tuple[Graph, EdgeIndex]] = OrderedDict()
        self._lock = threading.Lock()
        self._graphs_lock = threading.Lock()  # the background matching and the fog requests share the cache
        self.status: dict[str, dict] = {}  # user -> {"state": "running"/"done", "done": n, "total": n}

    # --- processing ---

    def process(self, user: str, folder: Path, activity_key: Callable[[str], str], activities: list[Activity] | None = None,
                announce: bool = False) -> int:
        """Match the activities not processed yet. Returns how many were processed.

        Only a run after an import of new activities (`announce`) celebrates the milestones it crosses; the
        others (the history at start-up, a new version of the matching, communes extracted later) catch up
        quietly: what they unlock is marked as seen."""
        with self._lock:
            if self.status.get(user, {}).get("state") == "running":
                return 0
            self.status[user] = {"state": "running", "done": 0, "total": 0}
        try:
            if activities is None:
                activities = ingest([folder / "raw"]).activities
            zones_file = folder / "privacy.json"
            zones = load_zones(zones_file) if zones_file.exists() else []
            self.place_in_communes()
            done = self.store.processed(user)
            known = self.store.cells(user)  # area already discovered: a new activity only adds its new cells
            todo = [a for a in activities if activity_key(a.source) not in done]
            todo.sort(key=lambda a: (_region(a) or (0, 0), a.start.isoformat() if a.start else ""))
            self.status[user]["total"] = len(todo)
            touched: set[str] = set()
            for i, act in enumerate(todo):
                touched |= self._activity(user, act, activity_key(act.source), zones, known)
                self.status[user]["done"] = i + 1
            self._totals(touched)
            if not announce:
                self.store.mark_seen(user, [a["id"] for a in self._achievements(user) if a["achieved"]] or ["-"])
            return len(todo)
        except Exception:
            log.exception("exploration of %s", user)
            raise
        finally:
            self.status[user]["state"] = "done"

    def place_in_communes(self) -> None:
        """Segments and places recorded before the communes were extracted: give them their commune now."""
        if not self.store.communes_count():
            return
        touched = set()
        for rowid, lat, lon, kind in self.store.without_commune():
            if kind.startswith("poi:"):
                poi = self.pois.get(kind[4:]) if self.pois is not None else None
                if poi is None:
                    continue
                lat, lon = poi.lat, poi.lon
            c = self.store.commune_at(lat, lon)
            if c is not None:
                self.store.set_commune("seg" if kind == "seg" else "poi", rowid, c.id)
                touched.add(c.id)
        rows = self.store.cells_without_commune()
        if rows:
            placed = self._cells_communes([(cx, cy) for _, cx, cy in rows])
            self.store.set_cells_commune((c, user, cx, cy) for (user, _, _), (cx, cy, c, _) in zip(rows, placed) if c is not None)
            touched |= {c for _, _, c, _ in placed if c is not None}
        self._totals(touched)

    def _activity(self, user: str, act: Activity, key: str, zones, known: set | None = None) -> set[str]:
        """Match one activity and add the area around it; returns the communes it touched."""
        timed = sum(1 for p in act.points if p.time) / max(len(act.points), 1)
        parts = moving_parts(mask(act, zones, DEFAULT_TRIM_M)) if timed >= TIMED_SHARE else []
        if not parts:
            self.store.add_activity(user, key, [], [])
            return set()
        known = known if known is not None else self.store.cells(user)
        new_cells = corridor_cells(parts) - known
        known |= new_cells
        cells = self._cells_communes(new_cells)
        graph = self._graph_for(parts)
        segments, communes = [], set()
        date = act.start.isoformat() if act.start else None
        if graph is not None:
            g, index = graph
            for idx in traversed_edges(g, parts, index):
                e = g.edges[idx]
                lat, lon = edge_midpoint(g, e)
                c = self.store.commune_at(lat, lon)
                if c:
                    communes.add(c.id)
                coords = [[round(g.coords[n][1], 6), round(g.coords[n][0], 6)] for n in e.nodes]
                segments.append(Segment(segment_key(e.nodes), round(e.length_m, 1), lat, lon, c.id if c else None, date, key, coords))
        pois = []
        if self.pois is not None:
            line = [[p.lon, p.lat] for part in parts for p in part]
            for poi in self.pois.along(line, POI_DISCOVERY_M, limit=500):
                c = self.store.commune_at(poi.lat, poi.lon)
                pois.append({"poi": poi.id, "name": poi.name, "category": poi.category, "kind": poi.kind,
                             "commune": c.id if c else None, "first_date": date})
        self.store.add_activity(user, key, segments, pois, cells)
        return communes | {c for _, _, c, _ in cells if c is not None}

    def _cells_communes(self, cells: Iterable[tuple[int, int]]) -> list[tuple[int, int, str | None, float]]:
        """(cx, cy, commune of its centre, m²) of each cell."""
        cells = list(cells)
        if not cells:
            return []
        centers = np.array([cell_center(cx, cy) for cx, cy in cells])
        lats, lons = centers[:, 0], centers[:, 1]
        found = np.full(len(cells), None, dtype=object)
        for c in self.store.communes_in((lons.min(), lats.min(), lons.max(), lats.max())):
            todo = np.flatnonzero((found == None) & (lons >= c.bbox[0]) & (lons <= c.bbox[2]) & (lats >= c.bbox[1]) & (lats <= c.bbox[3]))  # noqa: E711
            if len(todo):
                found[todo[in_polygons(lats[todo], lons[todo], c.polygons)]] = c.id
        return [(cx, cy, found[i], round(cell_area(cy), 2)) for i, (cx, cy) in enumerate(cells)]

    def _graph_for(self, parts) -> tuple[Graph, EdgeIndex] | None:
        with self._graphs_lock:
            return self._graph_for_locked(parts)

    def _graph_for_locked(self, parts) -> tuple[Graph, EdgeIndex] | None:
        """The graph of the aligned region(s) around these track parts (cached tiles only), with its index."""
        lats = [p.lat for part in parts for p in part]
        lons = [p.lon for part in parts for p in part]
        i0, i1 = math.floor(min(lats) / REGION_DEG), math.floor(max(lats) / REGION_DEG)
        j0, j1 = math.floor(min(lons) / REGION_DEG), math.floor(max(lons) / REGION_DEG)
        key = (i0, i1, j0, j1)
        if key in self._graphs:
            self._graphs.move_to_end(key)
            return self._graphs[key]
        per = round(REGION_DEG / TILE_DEG)
        tiles = [(i, j) for i in range(i0 * per, (i1 + 1) * per) for j in range(j0 * per, (j1 + 1) * per)]
        tiles = [t for t in tiles if tile_path(t, self.osm_dir).exists()]
        if not tiles:
            return None
        g = build_graph(load_cached_tiles(tiles, self.osm_dir))
        out = (g, EdgeIndex(g))
        self._graphs[key] = out
        while len(self._graphs) > 3:
            self._graphs.popitem(last=False)
        return out

    def graph_of_bbox(self, box) -> Graph | None:
        """Graph of the cached tiles of a small area (the fog view), kept for the next moves nearby."""
        with self._graphs_lock:
            return self._graph_of_bbox_locked(box)

    def _graph_of_bbox_locked(self, box) -> Graph | None:
        from ..routing.osm import tiles_for_bbox

        tiles = tuple(t for t in tiles_for_bbox(box[1], box[0], box[3], box[2]) if tile_path(t, self.osm_dir).exists())
        if not tiles:
            return None
        for key, (g, _) in self._graphs.items():
            if key == ("fog", tiles):
                return g
        g = build_graph(load_cached_tiles(list(tiles), self.osm_dir))
        self._graphs[("fog", tiles)] = (g, None)  # type: ignore[assignment]
        while len(self._graphs) > 4:
            self._graphs.popitem(last=False)
        return g

    def _totals(self, communes: set[str]) -> None:
        """Walkable length of the communes touched for the first time."""
        for cid in communes:
            c = self.store.commune(cid)
            if c is not None and c.total_m is None:
                total = walkable_total(c, self.osm_dir)
                if total:
                    self.store.set_total(cid, total)

    # --- what the user sees ---

    def _achievements(self, user: str) -> list[dict]:
        return self.achievements(self._communes(user), self.store.discovered(user))

    def summary(self, user: str) -> dict:
        communes = self._communes(user)
        achievements = self.achievements(communes, self.store.discovered(user))
        seen = set(self.store.settings(user)["seen"])
        return {
            "status": self.status.get(user, {"state": "idle"}),
            "totals": self.store.totals(user),
            "communes": communes,
            "achievements": achievements,
            "new": [a for a in achievements if a["achieved"] and a["id"] not in seen],
            "discovered": len(self.store.discovered(user)),
        }

    def _communes(self, user: str) -> list[dict]:
        communes = []
        for row in self.store.per_commune(user):
            c = self.store.commune(row["commune"])
            if c is None:
                continue
            pct = min(100.0, 100 * row["done_m"] / c.total_m) if c.total_m else None
            area = c.area_m2
            if area is None:
                area = round(polygons_area(c.polygons))
                self.store.set_area(c.id, area)
            area_pct = min(100.0, 100 * row["area_m2"] / area) if area else None
            communes.append({"id": c.id, "name": c.name, "pct": round(pct, 1) if pct is not None else None,
                             "done_m": row["done_m"], "total_m": c.total_m,
                             "area_pct": round(area_pct, 1) if area_pct is not None else None,
                             "area_done_m2": row["area_m2"], "area_m2": area,
                             "pois": row["pois"], "last": row["last"]})
        communes.sort(key=lambda c: (-(c["area_pct"] or 0), -c["done_m"]))
        return communes

    @staticmethod
    def achievements(communes: list[dict], discovered: list[dict]) -> list[dict]:
        """Milestones per commune (10/25/50/75/90 %) and badges (communes, summits, waterfalls…)."""
        out = []
        for c in communes:
            for m in MILESTONES:
                if c["pct"] is not None and c["pct"] >= m:
                    out.append({"id": f"commune:{c['id']}:{m}", "kind": "milestone", "title": f"{c['name']} : {m} % des chemins",
                                "detail": f"{m} % des chemins de {c['name']} parcourus", "achieved": True})
        kinds = Counter(p["kind"] for p in discovered)
        heritage = sum(1 for p in discovered if p["category"] == "heritage")
        badges = [
            ("communes", len(communes), (1, 5, 10, 25, 50), "commune explorée", "communes explorées"),
            ("peaks", kinds["peak"], (1, 5, 10, 25), "sommet atteint", "sommets atteints"),
            ("waterfalls", kinds["waterfall"], (1, 5, 10), "cascade découverte", "cascades découvertes"),
            ("viewpoints", kinds["viewpoint"], (1, 10, 25, 50), "point de vue", "points de vue"),
            ("heritage", heritage, (1, 10, 25, 50), "monument découvert", "monuments découverts"),
            ("lakes", kinds["lake"], (1, 5, 10), "lac découvert", "lacs découverts"),
        ]
        for name, count, steps, one, many in badges:
            for n in steps:
                out.append({"id": f"badge:{name}:{n}", "kind": "badge", "badge": name, "title": f"{n} {one if n == 1 else many}",
                            "detail": f"{count} à ce jour", "achieved": count >= n, "progress": min(count, n), "goal": n})
        return out

    def suggestions(self, user: str, home: tuple[float, float] | None) -> list[dict]:
        """Squares of ~1 km near home with the most walkable paths never run: « X km jamais courus à Y km »."""
        if home is None:
            return []
        lat0, lon0 = home
        k = 111_320 * math.cos(math.radians(lat0))
        r_lat, r_lon = SUGGEST_RADIUS_M / EARTH_M_PER_DEG_LAT, SUGGEST_RADIUS_M / k
        from ..routing.osm import tiles_for_bbox

        tiles = [t for t in tiles_for_bbox(lat0 - r_lat, lon0 - r_lon, lat0 + r_lat, lon0 + r_lon) if tile_path(t, self.osm_dir).exists()]
        if not tiles:
            return []
        g = build_graph(load_cached_tiles(tiles, self.osm_dir))
        done = self.store.segment_keys(user)
        cells: dict[tuple[int, int], list[float]] = {}
        for e in g.edges:
            if not explorable(e):
                continue
            lat, lon = edge_midpoint(g, e)
            dx, dy = (lon - lon0) * k, (lat - lat0) * EARTH_M_PER_DEG_LAT
            if math.hypot(dx, dy) > SUGGEST_RADIUS_M:
                continue
            cell = (math.floor(dx / SUGGEST_CELL_M), math.floor(dy / SUGGEST_CELL_M))
            totals = cells.setdefault(cell, [0.0, 0.0])
            totals[0] += e.length_m
            if segment_key(e.nodes) not in done:
                totals[1] += e.length_m
        # Closer is better (half the weight at ~4 km), and three different places, 2 km apart at least.
        def worth(item):
            (cx, cy), (_, new) = item
            return new * math.exp(-math.hypot((cx + 0.5) * SUGGEST_CELL_M, (cy + 0.5) * SUGGEST_CELL_M) / 6000)

        chosen: list = []
        for item in sorted(cells.items(), key=worth, reverse=True):
            (cx, cy), (_, new) = item
            if new < 1000:
                continue
            if all(math.hypot(cx - ox, cy - oy) * SUGGEST_CELL_M >= 2000 for (ox, oy), _ in chosen):
                chosen.append(item)
            if len(chosen) == 3:
                break
        out = []
        for (cx, cy), (total, new) in chosen:
            x, y = (cx + 0.5) * SUGGEST_CELL_M, (cy + 0.5) * SUGGEST_CELL_M
            out.append({"lat": round(lat0 + y / EARTH_M_PER_DEG_LAT, 5), "lon": round(lon0 + x / k, 5),
                        "new_km": round(new / 1000, 1), "total_km": round(total / 1000, 1),
                        "distance_km": round(math.hypot(x, y) / 1000, 1)})
        return out


def _region(a: Activity) -> tuple[int, int] | None:
    p = next((p for p in a.points), None)
    return (math.floor(p.lat / REGION_DEG), math.floor(p.lon / REGION_DEG)) if p else None
