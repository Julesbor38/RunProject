"""CLI: python -m app.ingest <file | folder | unzipped Strava archive> [-o out.geojson]"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Paris")

from .models import Activity
from .parsers import SUPPORTED, parse_file
from .strava import iter_strava_archive


def collect(target: Path):
    if target.is_dir() and (target / "activities.csv").exists():
        yield from iter_strava_archive(target)
    elif target.is_dir():
        for p in sorted(target.rglob("*")):
            if any(p.name.lower().endswith(ext) or p.name.lower().endswith(ext + ".gz") for ext in SUPPORTED):
                try:
                    yield parse_file(p)
                except Exception as e:  # noqa: BLE001
                    yield RuntimeError(f"{p.name}: {e}")
    else:
        yield parse_file(target)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("target", type=Path)
    ap.add_argument("-o", "--out", type=Path, help="write a GeoJSON FeatureCollection")
    args = ap.parse_args()

    acts: list[Activity] = []
    errors, no_gps = [], 0
    for item in collect(args.target):
        if isinstance(item, Exception):
            errors.append(item)
        elif not item.has_gps:
            no_gps += 1
        else:
            acts.append(item)

    for a in acts:
        d = a.duration_s
        start = a.start.astimezone(TZ) if a.start else None
        print(f"{start:%Y-%m-%d %H:%M}  {a.sport or '?':10} {a.distance_m/1000:6.1f} km  "
              f"D+ {a.ascent_m:5.0f} m  {d/60 if d else 0:5.0f} min  {len(a.points):6} pts  {a.name or ''}")
    total = sum(a.distance_m for a in acts) / 1000
    print(f"\n{len(acts)} activités GPS, {total:.0f} km au total | {no_gps} sans GPS | {len(errors)} erreurs")
    for e in errors[:10]:
        print("  !", e)

    if args.out:
        fc = {"type": "FeatureCollection", "features": [a.to_geojson() for a in acts]}
        args.out.write_text(json.dumps(fc))
        print(f"GeoJSON écrit : {args.out}")


if __name__ == "__main__":
    main()
