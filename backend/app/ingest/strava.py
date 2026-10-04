"""Import from an unzipped Strava archive (activities.csv + activities/)."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterator

from .models import Activity
from .parsers import parse_file

HIKE_TYPES = {"hike", "randonnée"}
ACTIVITY_TYPES = {"run", "trail run", "course à pied", "trail", "course"} | HIKE_TYPES


def iter_strava_archive(root: str | Path, types: set[str] = ACTIVITY_TYPES) -> Iterator[Activity | Exception]:
    """Yield parsed running and hiking activities. Errors are yielded (not raised) so one bad file doesn't stop the import."""
    root = Path(root)
    with open(root / "activities.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    header, rows = rows[0], rows[1:]
    col = _columns(header)
    for row in rows:
        atype = row[col["type"]].strip().lower()
        filename = row[col["file"]].strip() if col.get("file") is not None else ""
        if atype not in types or not filename:
            continue
        try:
            act = parse_file(root / filename)
        except Exception as e:  # noqa: BLE001
            yield RuntimeError(f"{filename}: {e}")
            continue
        act.source = f"strava:{row[col['id']]}"
        act.name = row[col["name"]] or act.name
        if atype in HIKE_TYPES:
            act.sport = "hike"
        else:
            act.sport = "trail_run" if "trail" in atype else (act.sport or "run")
        yield act


def _columns(header: list[str]) -> dict[str, int]:
    """Locate columns by name; Strava localizes headers (EN/FR) and duplicates some."""
    wanted = {
        "id": ("activity id", "id de l'activité"),
        "name": ("activity name", "nom de l'activité"),
        "type": ("activity type", "type d'activité"),
        "file": ("filename", "nom du fichier"),
    }
    out: dict[str, int] = {}
    low = [h.strip().lower() for h in header]
    for key, names in wanted.items():
        for i, h in enumerate(low):
            if h in names:
                out[key] = i
                break
    missing = {"id", "type", "file"} - out.keys()
    if missing:
        raise ValueError(f"activities.csv: columns not found {missing}. Header: {header[:15]}")
    out.setdefault("name", out["id"])
    return out
