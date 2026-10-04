"""CLI: python -m app.ingest <file | folder | unzipped Strava archive>... [-o out.geojson]"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from .pipeline import ingest
from .privacy import DEFAULT_TRIM_M, load_zones, mask

TZ = ZoneInfo("Europe/Paris")
DEFAULT_ZONES = Path(__file__).parents[3] / "data" / "privacy.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("targets", type=Path, nargs="+")
    ap.add_argument("-o", "--out", type=Path, help="write a GeoJSON FeatureCollection (privacy-masked)")
    ap.add_argument("--zones", type=Path, default=DEFAULT_ZONES, help="privacy zones JSON (default: data/privacy.json)")
    ap.add_argument("--trim", type=float, default=DEFAULT_TRIM_M, help="meters hidden around start/end")
    ap.add_argument("--raw", action="store_true", help="export unmasked tracks (personal use only)")
    args = ap.parse_args()

    res = ingest(args.targets)
    acts, errors = res.activities, res.errors

    for a in acts:
        d = a.duration_s
        start = a.start.astimezone(TZ) if a.start else None
        print(f"{start:%Y-%m-%d %H:%M}  {a.sport or '?':10} {a.distance_m/1000:6.1f} km  "
              f"D+ {a.ascent_m:5.0f} m  {d/60 if d else 0:5.0f} min  {len(a.points):6} pts  {a.name or ''}")
    total = sum(a.distance_m for a in acts) / 1000
    print(f"\n{len(acts)} activités GPS, {total:.0f} km au total | {res.no_gps} sans GPS | "
          f"{res.duplicates} doublons fusionnés | {len(errors)} erreurs")
    for e in errors[:10]:
        print("  !", e)

    if args.out:
        if args.raw:
            features = [a.to_geojson() for a in acts]
        else:
            zones = load_zones(args.zones) if args.zones.exists() else []
            features = [a.to_geojson(mask(a, zones, args.trim)) for a in acts]
        fc = {"type": "FeatureCollection", "features": features}
        args.out.write_text(json.dumps(fc))
        masking = "non masqué" if args.raw else f"masqué : {args.trim:.0f} m début/fin, {len(zones)} zone(s)"
        print(f"GeoJSON écrit : {args.out} ({masking})")


if __name__ == "__main__":
    main()
