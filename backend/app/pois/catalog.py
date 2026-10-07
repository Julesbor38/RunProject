"""Which OSM objects are notable places (« lieux notables »), their category, kind and importance score.

Categories (filters in the app): nature, water, heritage, park, utility. The kind picks the icon.
The score (0-100) decides from which zoom a place shows: big names first, details when zoomed in.
"""
from __future__ import annotations

import math

CATEGORIES = ("nature", "water", "heritage", "park", "utility")

# Tags kept with a place (for its sheet); everything else is dropped.
KEPT_TAGS = (
    "name", "name:fr", "ele", "wikidata", "wikipedia", "ref:mhs", "heritage", "heritage:operator",
    "mhs:inscription_date", "historic", "tourism", "natural", "leisure", "amenity", "waterway", "water",
    "boundary", "protect_class", "religion", "building", "drinking_water", "fee", "access", "shelter_type",
    "website", "description", "start_date", "opening_hours", "operator",
)

HERITAGE_KINDS = {
    "castle": "castle", "fort": "castle", "manor": "castle", "city_gate": "castle", "tower": "castle",
    "ruins": "ruins", "archaeological_site": "archaeological", "monument": "monument", "memorial": "memorial",
    "chapel": "church", "church": "church", "monastery": "church", "wayside_cross": "cross",
    "wayside_shrine": "cross", "bridge": "monument", "aqueduct": "monument", "mill": "monument",
}

# Kind -> base score.
BASE = {
    "viewpoint": 25, "peak": 30, "saddle": 10, "waterfall": 35, "spring": 10, "cave": 20, "rock": 15,
    "reserve": 25, "river": 15, "stream": 5, "lake": 20, "castle": 35, "ruins": 25, "archaeological": 20,
    "monument": 15, "memorial": 10, "church": 15, "cross": 3, "heritage": 10, "park": 15, "garden": 10,
    "drinking_water": 12, "toilets": 8, "shelter": 12, "hut": 25, "picnic": 6,
}

# Kinds that are worth showing without a name (a nameless lake or park is not).
NAMELESS_OK = {"viewpoint", "peak", "waterfall", "spring", "cave", "cross", "drinking_water", "toilets", "shelter", "picnic"}


def classify(tags: dict[str, str]) -> tuple[str, str] | None:
    """(category, kind) of a notable place, or None."""
    t = tags.get
    kind: tuple[str, str] | None = None
    if t("natural") == "waterfall" or t("waterway") == "waterfall":
        kind = ("water", "waterfall")
    elif t("tourism") == "viewpoint":
        kind = ("nature", "viewpoint")
    elif t("natural") in ("peak", "volcano"):
        kind = ("nature", "peak")
    elif t("natural") == "saddle":
        kind = ("nature", "saddle")
    elif t("natural") == "spring":
        kind = ("nature", "spring")
    elif t("natural") == "cave_entrance":
        kind = ("nature", "cave")
    elif t("natural") == "rock":
        kind = ("nature", "rock")
    elif t("leisure") == "nature_reserve" or t("boundary") == "protected_area":
        kind = ("nature", "reserve")
    elif t("waterway") in ("river", "stream"):
        kind = ("water", t("waterway"))  # type: ignore[assignment]
    elif t("natural") == "water" and t("water") not in ("wastewater", "basin", "reflecting_pool", "fountain"):
        kind = ("water", "lake")
    elif t("amenity") == "place_of_worship" and (t("historic") or t("heritage") or t("ref:mhs")):
        kind = ("heritage", "church")
    elif t("historic") and t("historic") not in ("no", "boundary_stone", "milestone", "district", "yes"):
        kind = ("heritage", HERITAGE_KINDS.get(t("historic"), "heritage"))  # type: ignore[arg-type]
    elif t("heritage") or t("ref:mhs") or t("historic") == "yes":
        kind = ("heritage", HERITAGE_KINDS.get(t("historic") or "", "heritage"))
    elif t("leisure") in ("park", "garden"):
        kind = ("park", t("leisure"))  # type: ignore[assignment]
    elif t("amenity") == "drinking_water" and t("drinking_water") != "no":
        kind = ("utility", "drinking_water")
    elif t("amenity") == "toilets" and t("access") not in ("private", "no"):
        kind = ("utility", "toilets")
    elif t("amenity") == "shelter":
        kind = ("utility", "shelter")
    elif t("tourism") in ("alpine_hut", "wilderness_hut"):
        kind = ("utility", "hut")
    elif t("tourism") == "picnic_site":
        kind = ("utility", "picnic")
    if kind is None:
        return None
    if not name_of(tags) and kind[1] not in NAMELESS_OK:
        return None
    if t("access") in ("private", "no") and kind[0] != "heritage":
        return None
    return kind


def name_of(tags: dict[str, str]) -> str:
    return tags.get("name:fr") or tags.get("name") or ""


def score(tags: dict[str, str], kind: str, area_m2: float = 0.0) -> float:
    """Importance, 0-100: Wikidata / Wikipédia, monument historique, summit height, named viewpoint, size."""
    s = BASE.get(kind, 10)
    if name_of(tags):
        s += 5
    if tags.get("wikidata"):
        s += 15
    if tags.get("wikipedia"):
        s += 10
    if tags.get("ref:mhs"):
        s += 15
    if kind == "peak":
        try:
            s += min(20.0, float(tags.get("ele", "").replace(",", ".").split()[0]) / 150)
        except (ValueError, IndexError):
            pass
    if kind == "viewpoint" and name_of(tags):
        s += 5
    if area_m2 > 1000:
        s += min(20.0, 4 * math.log10(area_m2 / 1000))
    return round(min(s, 100.0), 1)


def min_zoom(s: float) -> int:
    """From which map zoom a place of that score is shown."""
    for threshold, zoom in ((60, 9), (45, 11), (30, 12), (20, 13), (10, 14)):
        if s >= threshold:
            return zoom
    return 15


def kept(tags: dict[str, str]) -> dict[str, str]:
    return {k: tags[k] for k in KEPT_TAGS if k in tags}
