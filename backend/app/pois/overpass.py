"""Notable places outside the local extract (France): fetched from Overpass by 0.25° zone, in the background,
one zone at a time, kept in the place store. A zone is asked once (again after 30 min if it failed), and only
when someone looks at it: never on every map move.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable, Iterable

import httpx

from ..routing.osm import OVERPASS_URLS, USER_AGENT
from .catalog import classify, kept, min_zoom, name_of, score
from .extract import RIVER_CELL_DEG, remove_duplicates
from .store import EARTH_M_PER_DEG, Poi, PoiStore

ZONE_DEG = 0.25
RETRY_S = 30 * 60
SOURCE = "overpass"
MAX_ZONES_PER_REQUEST = 4

log = logging.getLogger(__name__)

QUERY = """[out:json][timeout:90];
(
  node["tourism"~"^(viewpoint|alpine_hut|wilderness_hut|picnic_site)$"]({b});
  node["natural"~"^(peak|volcano|saddle|waterfall|spring|cave_entrance|rock)$"]({b});
  nwr["waterway"="waterfall"]({b});
  nwr["leisure"~"^(nature_reserve|park|garden)$"]["name"]({b});
  relation["boundary"="protected_area"]["name"]({b});
  way["waterway"~"^(river|stream)$"]["name"]({b});
  nwr["natural"="water"]["name"]({b});
  nwr["historic"]({b});
  nwr["heritage"]({b});
  nwr["ref:mhs"]({b});
  node["amenity"~"^(drinking_water|toilets|shelter)$"]({b});
);
out tags center bb;"""


def zones_for(bbox: Iterable[float]) -> list[tuple[int, int]]:
    min_lon, min_lat, max_lon, max_lat = bbox
    return [
        (i, j)
        for i in range(math.floor(min_lat / ZONE_DEG), math.floor(max_lat / ZONE_DEG) + 1)
        for j in range(math.floor(min_lon / ZONE_DEG), math.floor(max_lon / ZONE_DEG) + 1)
    ]


def parse(elements: list[dict]) -> list[Poi]:
    """Overpass elements (`out tags center bb`) -> places (surfaces: their centre and approximate size)."""
    out: list[Poi] = []
    rivers: dict[tuple, Poi] = {}
    for el in elements:
        tags = el.get("tags", {})
        found = classify(tags)
        if found is None:
            continue
        category, kind = found
        centre = el.get("center") or el
        if "lat" not in centre:
            continue
        lat, lon = centre["lat"], centre["lon"]
        area = 0.0
        b = el.get("bounds")
        if b and kind not in ("river", "stream") and el["type"] != "node":
            w = (b["maxlon"] - b["minlon"]) * EARTH_M_PER_DEG * math.cos(math.radians(lat))
            h = (b["maxlat"] - b["minlat"]) * EARTH_M_PER_DEG
            area = 0.6 * w * h  # a surface fills ~60 % of its box
        s = score(tags, kind, area)
        poi = Poi(f"{el['type'][0]}{el['id']}", lat, lon, category, kind, name_of(tags), s, min_zoom(s), kept(tags),
                  round(math.sqrt(area / math.pi)) if area else 0, SOURCE)
        if kind in ("river", "stream"):
            rivers.setdefault((poi.name, math.floor(lat / RIVER_CELL_DEG), math.floor(lon / RIVER_CELL_DEG)), poi)
        else:
            out.append(poi)
    return out + list(rivers.values())


class OverpassZones:
    """Fetches the zones not covered by the local extract, one at a time, in the background."""

    def __init__(self, store: PoiStore, covered: Callable[[tuple[int, int]], bool], post=httpx.post):
        self.store = store
        self.covered = covered  # zone -> in the local extract
        self.post = post
        self._queue: list[tuple[int, int]] = []
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None

    def want(self, bbox: Iterable[float]) -> int:
        """Queue the zones of this area that are neither local nor fetched (nor failed recently). Returns how many."""
        now = time.time()
        todo = []
        for z in zones_for(bbox)[: MAX_ZONES_PER_REQUEST * 4]:
            if self.covered(z):
                continue
            state = self.store.zone_state(_key(z))
            if state and (state[1] or now - state[0] < RETRY_S):
                continue
            todo.append(z)
        todo = todo[:MAX_ZONES_PER_REQUEST]
        with self._lock:
            for z in todo:
                if z not in self._queue:
                    self._queue.append(z)
            if self._queue and (self._worker is None or not self._worker.is_alive()):
                self._worker = threading.Thread(target=self._run, name="pois-overpass", daemon=True)
                self._worker.start()
        return len(todo)

    def _run(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    return
                zone = self._queue.pop(0)
            self.fetch(zone)
            time.sleep(2)  # Overpass usage policy: one request at a time, not in a burst

    def fetch(self, zone: tuple[int, int]) -> int:
        i, j = zone
        b = f"{i * ZONE_DEG},{j * ZONE_DEG},{(i + 1) * ZONE_DEG},{(j + 1) * ZONE_DEG}"
        query = QUERY.format(b=b)
        for url in OVERPASS_URLS:
            try:
                r = self.post(url, data={"data": query}, headers={"User-Agent": USER_AGENT}, timeout=120)
                r.raise_for_status()
                added = self.store.add(parse(r.json().get("elements", [])))
                remove_duplicates(self.store, SOURCE)
                self.store.zone_put(_key(zone), time.time(), True)
                log.info("overpass places: zone %s, %d new", zone, added)
                return added
            except (httpx.HTTPError, ValueError) as e:
                log.warning("overpass places %s: %s", url, e)
        self.store.zone_put(_key(zone), time.time(), False)
        return 0


def _key(zone: tuple[int, int]) -> str:
    return f"{zone[0]},{zone[1]}"
