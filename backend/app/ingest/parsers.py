"""Parsers for .fit / .gpx / .tcx files (optionally gzip-compressed)."""
from __future__ import annotations

import gzip
import io
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import fitdecode
import gpxpy

from .models import Activity, TrackPoint

SEMICIRCLE = 180 / 2**31
SUPPORTED = (".fit", ".gpx", ".tcx")


def _read_bytes(path: Path) -> tuple[bytes, str]:
    """Return (content, real_extension), transparently un-gzipping."""
    data = path.read_bytes()
    suffixes = [s.lower() for s in path.suffixes]
    if suffixes and suffixes[-1] == ".gz":
        data = gzip.decompress(data)
        suffixes = suffixes[:-1]
    ext = suffixes[-1] if suffixes else ""
    return data, ext


def parse_file(path: str | Path) -> Activity:
    path = Path(path)
    data, ext = _read_bytes(path)
    if ext == ".fit":
        return _parse_fit(data, str(path))
    if ext == ".gpx":
        return _parse_gpx(data, str(path))
    if ext == ".tcx":
        return _parse_tcx(data, str(path))
    raise ValueError(f"Unsupported format: {path.name}")


def _normalize_sport(sport: str | None, sub_sport: str | None = None) -> str | None:
    s = (sport or "").lower().replace(" ", "_")
    sub = (sub_sport or "").lower()
    if "trail" in s or sub == "trail":
        return "trail_run"
    if s in ("running", "run", "1"):
        return "run"
    return s or None


def _parse_fit(data: bytes, source: str) -> Activity:
    act = Activity(source=source)
    sport = sub_sport = None
    with fitdecode.FitReader(io.BytesIO(data)) as fr:
        for frame in fr:
            if not isinstance(frame, fitdecode.FitDataMessage):
                continue
            if frame.name == "record":
                lat = _get(frame, "position_lat")
                lon = _get(frame, "position_long")
                if lat is None or lon is None:
                    continue
                ele = _get(frame, "enhanced_altitude")
                if ele is None:
                    ele = _get(frame, "altitude")
                act.points.append(TrackPoint(
                    time=_get(frame, "timestamp"),
                    lat=lat * SEMICIRCLE, lon=lon * SEMICIRCLE,
                    ele=ele, hr=_get(frame, "heart_rate"),
                ))
            elif frame.name in ("session", "sport"):
                sport = _get(frame, "sport") or sport
                sub_sport = _get(frame, "sub_sport") or sub_sport
                if frame.name == "session":
                    act.start = _get(frame, "start_time") or act.start
    act.sport = _normalize_sport(str(sport) if sport else None, str(sub_sport) if sub_sport else None)
    if act.start is None and act.points:
        act.start = act.points[0].time
    return act


def _get(frame, name):
    return frame.get_value(name) if frame.has_field(name) else None


def _parse_gpx(data: bytes, source: str) -> Activity:
    gpx = gpxpy.parse(data.decode("utf-8", errors="replace"))
    act = Activity(source=source)
    for trk in gpx.tracks:
        act.name = act.name or trk.name
        act.sport = act.sport or _normalize_sport(trk.type)
        for seg in trk.segments:
            for p in seg.points:
                hr = None
                for ext in p.extensions:          # Garmin TrackPointExtension
                    for el in ext.iter():
                        if el.tag.endswith("hr") and el.text:
                            hr = int(float(el.text))
                act.points.append(TrackPoint(p.time, p.latitude, p.longitude, p.elevation, hr))
    act.start = act.points[0].time if act.points else None
    return act


def _parse_tcx(data: bytes, source: str) -> Activity:
    root = ET.fromstring(data.lstrip())
    ns = {"t": "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"}
    act = Activity(source=source)
    a = root.find(".//t:Activity", ns)
    if a is not None:
        act.sport = _normalize_sport(a.get("Sport"))
    for tp in root.iterfind(".//t:Trackpoint", ns):
        lat = tp.find("t:Position/t:LatitudeDegrees", ns)
        lon = tp.find("t:Position/t:LongitudeDegrees", ns)
        if lat is None or lon is None:
            continue
        t = tp.find("t:Time", ns)
        ele = tp.find("t:AltitudeMeters", ns)
        hr = tp.find("t:HeartRateBpm/t:Value", ns)
        act.points.append(TrackPoint(
            time=datetime.fromisoformat(t.text.replace("Z", "+00:00")) if t is not None else None,
            lat=float(lat.text), lon=float(lon.text),
            ele=float(ele.text) if ele is not None else None,
            hr=int(hr.text) if hr is not None else None,
        ))
    act.start = act.points[0].time if act.points else None
    return act
