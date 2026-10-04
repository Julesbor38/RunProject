"""HTTP API: serves the ingested activities as privacy-masked GeoJSON.

No database yet: activities are read from data/raw at startup (cached in data/cache/) and kept in memory.
Run with: uvicorn app.api:app --reload
"""
from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .ingest import load_zones, mask
from .ingest.models import TrackPoint
from .ingest.pipeline import ingest
from .ingest.privacy import DEFAULT_TRIM_M
from .ingest.simplify import simplify
from .routing import Preferences, RoutingError, RoutingService
from .routing.elevation import Dem

DATA_DIR = Path(os.environ.get("TRAILMAP_DATA", Path(__file__).parents[2] / "data"))
SIMPLIFY_TOLERANCE_M = 5.0
PREFETCH_OSM = os.environ.get("TRAILMAP_PREFETCH", "1") != "0"

state: dict = {}
logging.getLogger("app").setLevel(logging.INFO)
logging.getLogger("app").addHandler(logging.StreamHandler())


def build_feature_collection(data_dir: Path) -> dict:
    res = ingest([data_dir / "raw"])
    zones_file = data_dir / "privacy.json"
    zones = load_zones(zones_file) if zones_file.exists() else []
    features = []
    for i, act in enumerate(sorted(res.activities, key=lambda a: a.start or 0)):
        segments = [simplify(s, SIMPLIFY_TOLERANCE_M) for s in mask(act, zones, DEFAULT_TRIM_M)]
        feature = act.to_geojson(segments)
        feature["geometry"]["coordinates"] = [[_lonlat(p) for p in s] for s in segments]
        feature["id"] = i
        feature["properties"]["duration_s"] = act.duration_s
        features.append(feature)
    return {
        "type": "FeatureCollection",
        "features": features,
        "stats": {
            "activities": len(features),
            "no_gps": res.no_gps,
            "duplicates": res.duplicates,
            "errors": [str(e) for e in res.errors],
        },
    }


def _lonlat(p: TrackPoint) -> list[float]:
    return [round(p.lon, 6), round(p.lat, 6)]


def load_cached(data_dir: Path, force: bool = False) -> dict:
    """Ingest is slow (~20 s for a full Strava export): reuse data/cache/ while inputs are unchanged."""
    cache = data_dir / "cache" / "activities.geojson"
    inputs = [p for p in (data_dir / "raw").rglob("*") if p.is_file()] + [data_dir / "privacy.json"]
    newest = max((p.stat().st_mtime for p in inputs if p.exists()), default=0)
    if not force and cache.exists() and cache.stat().st_mtime > newest:
        return json.loads(cache.read_text())
    fc = build_feature_collection(data_dir)
    cache.parent.mkdir(exist_ok=True)
    cache.write_text(json.dumps(fc))
    return fc


def routing_service(fc: dict) -> RoutingService:
    tracks = [line for f in fc["features"] for line in f["geometry"]["coordinates"]]
    return RoutingService(DATA_DIR / "osm", tracks, Dem(DATA_DIR / "dem"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    state["activities"] = load_cached(DATA_DIR)
    state["routing"] = routing_service(state["activities"])
    if PREFETCH_OSM:
        state["routing"].start_prefetch()
    yield


app = FastAPI(title="Trail Map", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["GET", "POST"])


@app.get("/api/activities")
def activities() -> dict:
    return state["activities"]


@app.post("/api/reload")
def reload() -> dict:
    state["activities"] = load_cached(DATA_DIR, force=True)
    state["routing"] = routing_service(state["activities"])
    return state["activities"]["stats"]


class PreferencesIn(BaseModel):
    nature: float = Field(0.5, ge=0, le=1)
    avoid_traffic: float = Field(0.7, ge=0, le=1)
    lit: float = Field(0.0, ge=0, le=1)
    familiarity: float = Field(0.0, ge=-1, le=1)
    avoid_steps: float = Field(0.3, ge=0, le=1)
    hills: float = Field(0.0, ge=-1, le=1)


class RouteRequest(BaseModel):
    start: tuple[float, float]  # (lon, lat)
    end: tuple[float, float] | None = None  # None: loop back to start
    distance_km: float | None = Field(None, gt=0)
    ascent_min_m: float | None = Field(None, ge=0)  # wanted D+ range, loops only
    ascent_max_m: float | None = Field(None, ge=0)
    preferences: PreferencesIn = PreferencesIn()


@app.get("/api/routing/status")
def routing_status() -> dict:
    """Progress of the background OSM download around the user's running areas."""
    return state["routing"].status()


@app.post("/api/routes")
def routes(req: RouteRequest) -> dict:
    """Generate up to 3 loops (or one A-to-B route) matching the preferences."""
    try:
        return state["routing"].generate(
            req.start,
            Preferences(**req.preferences.model_dump()),
            distance_m=req.distance_km * 1000 if req.distance_km else None,
            end=req.end,
            ascent_range=_ascent_range(req),
        )
    except RoutingError as e:
        raise HTTPException(422, str(e)) from e


def _ascent_range(req: RouteRequest) -> tuple[float, float] | None:
    if req.ascent_min_m is None and req.ascent_max_m is None:
        return None
    lo = req.ascent_min_m or 0.0
    hi = req.ascent_max_m if req.ascent_max_m is not None else 10_000.0
    if hi < lo:
        raise HTTPException(422, "D+ max inférieur au D+ min")
    return lo, hi
