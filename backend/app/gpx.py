"""GPX 1.1 export of routes, shaped so that phone share sheets offer GPX apps (COROS) to open it.

iOS picks the apps from the file type: the file must end in exactly `.gpx`, be served as
`application/gpx+xml` with `Content-Disposition: attachment`, and be a plain GPX 1.1 document.
"""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from xml.sax.saxutils import escape, quoteattr

from fastapi import Response

MEDIA_TYPE = "application/gpx+xml"
CREATOR = "Trail Map"
NAMESPACE = "http://www.topografix.com/GPX/1/1"


def to_gpx(
    name: str,
    coords: Sequence[Sequence[float]],
    waypoints: Iterable[tuple[str, float, float]] = (),
    time: datetime | None = None,
) -> str:
    """One track (`coords`: [lon, lat] or [lon, lat, ele]) and optional named waypoints (name, lon, lat)."""
    time = (time or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<gpx version="1.1" creator={quoteattr(CREATOR)} xmlns="{NAMESPACE}"'
        ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
        f' xsi:schemaLocation="{NAMESPACE} {NAMESPACE}/gpx.xsd">',
        f"  <metadata><name>{escape(name)}</name><time>{time}</time></metadata>",
    ]
    # Schema order: metadata, wpt*, rte*, trk*.
    for wpt_name, lon, lat in waypoints:
        lines.append(f'  <wpt lat="{lat:.6f}" lon="{lon:.6f}"><name>{escape(wpt_name)}</name></wpt>')
    lines += ["  <trk>", f"    <name>{escape(name)}</name>", "    <trkseg>"]
    for c in coords:
        lon, lat = c[0], c[1]
        ele = f"<ele>{c[2]:.1f}</ele>" if len(c) > 2 and c[2] is not None else ""
        lines.append(f'      <trkpt lat="{lat:.6f}" lon="{lon:.6f}">{ele}</trkpt>')
    lines += ["    </trkseg>", "  </trk>", "</gpx>", ""]
    return "\n".join(lines)


def filename(name: str) -> str:
    """ASCII-only, no spaces: `Trail Map boucle 10,0 km` -> `trail-map-boucle-10-0-km.gpx`."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:60].strip("-")
    return f"{slug or 'trail-map'}.gpx"


def response(name: str, coords: Sequence[Sequence[float]]) -> Response:
    return Response(
        to_gpx(name, coords).encode("utf-8"),
        media_type=MEDIA_TYPE,  # Starlette adds no charset to non-text types: the XML header declares UTF-8
        headers={
            "Content-Disposition": f'attachment; filename="{filename(name)}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )
