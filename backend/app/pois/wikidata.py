"""Wikidata details for places with a `wikidata` tag: short French description, French Wikipédia link,
Commons picture (thumbnail) with its author and licence. Grouped requests (up to 50 ids), an explicit
User-Agent (Wikimedia's policy), cached 30 days in the place store (1 day after a failure).
"""
from __future__ import annotations

import html
import logging
import re
import threading
import time
from collections.abc import Iterable

import httpx

from .store import PoiStore

USER_AGENT = "RunProject/0.1 (https://github.com/Julesbor38/RunProject; trail running map, self-hosted)"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
BATCH = 50
TTL_S = 30 * 86400
FAILED_TTL_S = 86400
THUMB_PX = 480
QID = re.compile(r"^Q\d+$")

log = logging.getLogger(__name__)


class Wikidata:
    def __init__(self, store: PoiStore, client: httpx.Client | None = None):
        self.store = store
        self.client = client or httpx.Client(timeout=10, headers={"User-Agent": USER_AGENT})
        self._queue: set[str] = set()
        self._cond = threading.Condition()
        self._worker: threading.Thread | None = None

    def get(self, qid: str) -> dict | None:
        """Details of one entity (cache, else a request now). None if unknown or unreachable."""
        if not QID.match(qid):
            return None
        cached = self._cached(qid)
        if cached is not None:
            return cached or None
        self.fetch([qid])
        cached = self._cached(qid)
        return cached or None

    def prefetch(self, qids: Iterable[str]) -> None:
        """In the background, in groups: the entities of the places on screen, so their sheets open at once."""
        todo = {q for q in qids if QID.match(q) and self._cached(q) is None}
        if not todo:
            return
        with self._cond:
            self._queue |= todo
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._run, name="wikidata", daemon=True)
                self._worker.start()
            self._cond.notify()

    def _run(self) -> None:
        while True:
            with self._cond:
                if not self._queue:
                    return
                batch = [self._queue.pop() for _ in range(min(BATCH, len(self._queue)))]
            self.fetch(batch)
            time.sleep(1)  # gentle with Wikimedia

    def _cached(self, qid: str) -> dict | None:
        """The cached details ({} for « nothing / failed recently »), or None to fetch."""
        hit = self.store.wikidata_get(qid)
        if hit is None:
            return None
        data, fetched = hit
        ttl = FAILED_TTL_S if data.get("_failed") else TTL_S
        if time.time() - fetched > ttl:
            return None
        return {} if data.get("_failed") else data

    def fetch(self, qids: list[str]) -> None:
        """One grouped Wikidata request (then one Commons request for their pictures), stored in the cache."""
        now = time.time()
        try:
            r = self.client.get(
                WIKIDATA_API,
                params={
                    "action": "wbgetentities", "ids": "|".join(qids), "props": "descriptions|sitelinks|claims",
                    "languages": "fr", "sitefilter": "frwiki", "format": "json",
                },
            )
            r.raise_for_status()
            entities = r.json().get("entities", {})
        except (httpx.HTTPError, ValueError) as e:
            log.warning("wikidata: %s", e)
            for q in qids:
                self.store.wikidata_put(q, {"_failed": True}, now)
            return
        details: dict[str, dict] = {}
        pictures: dict[str, str] = {}
        for q in qids:
            ent = entities.get(q, {})
            d: dict = {}
            desc = ent.get("descriptions", {}).get("fr", {}).get("value")
            if desc:
                d["description"] = desc
            title = ent.get("sitelinks", {}).get("frwiki", {}).get("title")
            if title:
                d["wikipedia"] = "https://fr.wikipedia.org/wiki/" + title.replace(" ", "_")
            try:
                pictures[q] = ent["claims"]["P18"][0]["mainsnak"]["datavalue"]["value"]
            except (KeyError, IndexError, TypeError):
                pass
            details[q] = d
        for q, image in self._pictures(pictures).items():
            details[q]["image"] = image
        for q, d in details.items():
            self.store.wikidata_put(q, d, now)

    def _pictures(self, files: dict[str, str]) -> dict[str, dict]:
        """Commons thumbnails with author and licence: {qid: {thumb, page, author, license, license_url}}."""
        if not files:
            return {}
        try:
            r = self.client.get(
                COMMONS_API,
                params={
                    "action": "query", "titles": "|".join(f"File:{f}" for f in files.values()), "prop": "imageinfo",
                    "iiprop": "url|extmetadata", "iiurlwidth": THUMB_PX, "format": "json",
                },
            )
            r.raise_for_status()
            pages = r.json().get("query", {}).get("pages", {}).values()
        except (httpx.HTTPError, ValueError) as e:
            log.warning("commons: %s", e)
            return {}
        by_title = {}
        for page in pages:
            info = (page.get("imageinfo") or [{}])[0]
            meta = info.get("extmetadata", {})
            if not info.get("thumburl"):
                continue
            by_title[page.get("title", "").removeprefix("File:").replace("_", " ")] = {
                "thumb": info["thumburl"],
                "page": info.get("descriptionurl"),
                "author": _text(meta.get("Artist", {}).get("value", "")) or "auteur inconnu",
                "license": _text(meta.get("LicenseShortName", {}).get("value", "")) or "licence inconnue",
                "license_url": meta.get("LicenseUrl", {}).get("value"),
            }
        return {q: by_title[f.replace("_", " ")] for q, f in files.items() if f.replace("_", " ") in by_title}


def _text(value: str) -> str:
    """Commons metadata is HTML: plain text, short."""
    return html.unescape(re.sub(r"<[^>]+>", "", value)).strip()[:200]
