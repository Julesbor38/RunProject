"""Full ingest pipeline: collect files, parse, clean, dedupe."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from .clean import clean
from .dedup import dedupe
from .models import Activity
from .parsers import SUPPORTED, parse_file
from .strava import iter_strava_archive


@dataclass
class IngestResult:
    activities: list[Activity] = field(default_factory=list)
    errors: list[Exception] = field(default_factory=list)
    no_gps: int = 0
    duplicates: int = 0


def collect(target: Path) -> Iterator[Activity | Exception]:
    """Yield activities from a file, a folder, or an unzipped Strava archive.

    Folders are walked recursively; a subfolder holding an `activities.csv` is
    read as a Strava archive and its files are not read a second time.
    """
    if target.is_dir() and (target / "activities.csv").exists():
        yield from iter_strava_archive(target)
    elif target.is_dir():
        archives = sorted(p.parent for p in target.rglob("activities.csv"))
        for archive in archives:
            yield from iter_strava_archive(archive)
        for p in sorted(target.rglob("*")):
            if any(a in p.parents for a in archives) or not _supported(p):
                continue
            yield from _parse(p)
    else:
        yield from _parse(target)


def ingest(targets: list[Path]) -> IngestResult:
    res = IngestResult()
    acts: list[Activity] = []
    for target in targets:
        for item in collect(target):
            if isinstance(item, Exception):
                res.errors.append(item)
                continue
            item = clean(item)
            if item.has_gps:
                acts.append(item)
            else:
                res.no_gps += 1
    res.activities, res.duplicates = dedupe(acts)
    return res


def _supported(p: Path) -> bool:
    name = p.name.lower()
    return p.is_file() and any(name.endswith(ext) or name.endswith(ext + ".gz") for ext in SUPPORTED)


def _parse(p: Path) -> Iterator[Activity | Exception]:
    try:
        yield parse_file(p)
    except Exception as e:  # noqa: BLE001
        yield RuntimeError(f"{p.name}: {e}")
