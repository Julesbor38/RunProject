"""The user's ratings of their activities, per criterion (1 to 5, 5 = best), kept in data/ratings.json.

Keyed by the activity's stable key (Strava id, or file name) and by user, so they survive
re-imports and are ready for several users. Later (step 3) they will be carried over to the
OSM segments the activity went along.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

# (key, label): every criterion reads "higher is better".
CRITERIA = [
    ("safety", "Sécurité"),
    ("lighting", "Éclairage"),
    ("scenery", "Beauté du paysage"),
    ("pleasure", "Plaisir"),
    ("upkeep", "Entretien des chemins"),
    ("shelter", "Abri (ombre, pluie)"),
    ("quiet", "Tranquillité (peu de monde)"),
    ("traffic", "Peu de circulation"),
]
CRITERIA_KEYS = {k for k, _ in CRITERIA}

_lock = threading.Lock()


def _path(data_dir: Path) -> Path:
    return data_dir / "ratings.json"


def _read(data_dir: Path) -> dict:
    p = _path(data_dir)
    return json.loads(p.read_text()) if p.exists() else {}


def for_user(data_dir: Path, user: str) -> dict:
    """{activity key: {"scores": {criterion: 1..5}, "comment": str, "updated": epoch}}"""
    return {key: by_user[user] for key, by_user in _read(data_dir).items() if user in by_user}


def save(data_dir: Path, user: str, key: str, scores: dict[str, int], comment: str) -> dict:
    rating = {"scores": scores, "comment": comment, "updated": int(time.time())}
    with _lock:
        data = _read(data_dir)
        data.setdefault(key, {})[user] = rating
        _write(data_dir, data)
    return rating


def delete(data_dir: Path, user: str, key: str) -> bool:
    with _lock:
        data = _read(data_dir)
        if data.get(key, {}).pop(user, None) is None:
            return False
        if not data[key]:
            del data[key]
        _write(data_dir, data)
        return True


def _write(data_dir: Path, data: dict) -> None:
    p = _path(data_dir)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    tmp.replace(p)
