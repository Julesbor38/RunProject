"""HTTP API: serves the ingested activities as privacy-masked GeoJSON.

No database yet: activities are read from data/raw at startup (cached in data/cache/) and kept in memory.
Dev: uvicorn app.api:app --reload (the front is served by Vite on :5173).
Production: build the front (npm run build), then uvicorn app.api:app --host 127.0.0.1 --port 8000
serves both the API and frontend/dist on a single port (see SELF-HOST.md).
"""
from __future__ import annotations

import json
import logging
import math
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Path as PathParam
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import frequency, gpx
from .ingest import load_zones, mask
from .ingest.models import TrackPoint
from .ingest.pipeline import ingest
from .ingest.privacy import DEFAULT_TRIM_M
from .ingest.simplify import simplify
from .routing import Preferences, RoutingError, RoutingService
from .routing.osm import TILE_DEG, load_cached_tiles, tile_path
from .routing.elevation import Dem
from .routing.job import Cancelled, Job

DATA_DIR = Path(os.environ.get("TRAILMAP_DATA", Path(__file__).parents[2] / "data"))
SIMPLIFY_TOLERANCE_M = 5.0
PREFETCH_OSM = os.environ.get("TRAILMAP_PREFETCH", "1") != "0"
# Generated routes kept for GET /api/routes/{route_id}/gpx (the newest ones only).
MAX_SAVED_ROUTES = 300
# Built front (npm run build); served by the API when present, so production needs a single port.
FRONTEND_DIST = Path(os.environ.get("TRAILMAP_FRONTEND_DIST", Path(__file__).parents[2] / "frontend" / "dist"))

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


def load_frequency(data_dir: Path, fc: dict, force: bool = False) -> dict:
    """Pass counts drawn on the OSM ways, cached in data/cache/.

    Recomputed when the activities cache changes, when the algorithm settings change,
    or when more OSM tiles around the tracks have been downloaded since.
    """
    activities = data_dir / "cache" / "activities.geojson"
    cache = data_dir / "cache" / "frequency.geojson"
    tiles = sorted(
        {(math.floor(lat / TILE_DEG), math.floor(lon / TILE_DEG)) for f in fc["features"] for line in f["geometry"]["coordinates"] for lon, lat in line}
    )
    osm_dir = data_dir / "osm"
    osm_key = " ".join(f"{i},{j}" for i, j in tiles if tile_path((i, j), osm_dir).exists())
    if not force and cache.exists() and activities.exists() and cache.stat().st_mtime >= activities.stat().st_mtime:
        cached = json.loads(cache.read_text())
        if cached.get("signature") == frequency.SIGNATURE and cached.get("osm") == osm_key:
            return cached
    ways = frequency.osm_lines(load_cached_tiles(tiles, osm_dir)) if osm_key else None
    out = frequency.frequency_collection(fc, ways, osm_key)
    cache.parent.mkdir(exist_ok=True)
    cache.write_text(json.dumps(out))
    return out


def routing_service(fc: dict) -> RoutingService:
    tracks = [line for f in fc["features"] for line in f["geometry"]["coordinates"]]
    return RoutingService(DATA_DIR / "osm", tracks, Dem(DATA_DIR / "dem"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    state["activities"] = load_cached(DATA_DIR)
    state["frequency"] = load_frequency(DATA_DIR, state["activities"])
    state["routing"] = routing_service(state["activities"])
    if PREFETCH_OSM:
        # New OSM tiles let more of the tracks be drawn on the streets themselves.
        state["routing"].start_prefetch(on_done=lambda: state.update(frequency=load_frequency(DATA_DIR, state["activities"])))
    state["started_at"] = time.time()
    yield


app = FastAPI(title="Trail Map", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["GET", "POST"])


@app.api_route("/api/health", methods=["GET", "HEAD"])
def health() -> dict:
    """Liveness and a summary of what is loaded (no track data). Used by deploy-local.sh and monitoring."""
    stats = state["activities"]["stats"]
    return {
        "status": "ok",
        "uptime_s": round(time.time() - state["started_at"]),
        "activities": stats["activities"],
        "ingest_errors": len(stats["errors"]),
        "frequency_ways": len(state["frequency"]["features"]),
        "routing": {**state["routing"].status(), "jobs_running": len(state.get("jobs", {}))},
        "frontend": (FRONTEND_DIST / "index.html").is_file(),
    }


@app.get("/api/activities")
def activities() -> dict:
    return state["activities"]


@app.get("/api/frequency")
def frequency_map() -> dict:
    """Track pieces with the number of distinct activities that went along them."""
    return state["frequency"]


@app.post("/api/reload")
def reload() -> dict:
    state["activities"] = load_cached(DATA_DIR, force=True)
    state["frequency"] = load_frequency(DATA_DIR, state["activities"], force=True)
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
    distance_km: float | None = Field(None, gt=0)  # loop length, or target length A to B (else the best route)
    ascent_min_m: float | None = Field(None, ge=0)  # wanted D+ range (with distance_km)
    ascent_max_m: float | None = Field(None, ge=0)
    preferences: PreferencesIn = PreferencesIn()
    request_id: str | None = Field(None, max_length=64)  # lets the client follow and cancel the generation


@app.get("/api/routing/status")
def routing_status() -> dict:
    """Progress of the background OSM download around the user's running areas."""
    return state["routing"].status()


@app.post("/api/routes")
def routes(req: RouteRequest) -> dict:
    """Generate up to 3 loops (or one A-to-B route) matching the preferences."""
    jobs = state.setdefault("jobs", {})
    # setdefault: a cancel that arrived before the request itself still applies.
    job = jobs.setdefault(req.request_id, Job()) if req.request_id else Job()
    try:
        out = state["routing"].generate(
            req.start,
            Preferences(**req.preferences.model_dump()),
            distance_m=req.distance_km * 1000 if req.distance_km else None,
            end=req.end,
            ascent_range=_ascent_range(req),
            job=job,
        )
    except RoutingError as e:
        raise HTTPException(422, str(e)) from e
    except Cancelled as e:
        raise HTTPException(409, "génération annulée") from e
    finally:
        if req.request_id:
            jobs.pop(req.request_id, None)
    kind = "boucle" if req.end is None else "itinéraire"
    for f in out["features"]:
        save_route(f, f"Trail Map {kind} {f['properties']['distance_m'] / 1000:.1f} km".replace(".", ","))
    return out


def save_route(feature: dict, name: str) -> None:
    """Keeps the route in data/routes/ and gives it a `route_id`, a `name` and its GPX `gpx_filename`."""
    route_id = uuid.uuid4().hex
    feature["properties"].update(route_id=route_id, name=name, gpx_filename=gpx.filename(name))
    folder = DATA_DIR / "routes"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{route_id}.json").write_text(json.dumps({"name": name, "coordinates": feature["geometry"]["coordinates"]}))
    saved = sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime)
    for old in saved[:-MAX_SAVED_ROUTES]:
        old.unlink(missing_ok=True)


@app.get("/api/routes/{route_id}/gpx")
def route_gpx(route_id: str = PathParam(pattern="^[0-9a-f]{32}$")):
    """GPX of a generated route, as a download (what Safari on iOS turns into « Ouvrir dans… »)."""
    file = DATA_DIR / "routes" / f"{route_id}.json"
    if not file.is_file():
        raise HTTPException(404, "itinéraire inconnu ou expiré, régénérez-le")
    saved = json.loads(file.read_text())
    return gpx.response(saved["name"], saved["coordinates"])


class GpxRequest(BaseModel):
    name: str = Field("Trail Map", min_length=1, max_length=100)
    # [lon, lat] or [lon, lat, ele]
    coordinates: list[tuple[float, float] | tuple[float, float, float]] = Field(min_length=2, max_length=50_000)


@app.post("/api/routes/gpx")
def gpx_of(req: GpxRequest):
    """GPX of any proposed route sent by the client."""
    if any(not (-180 <= c[0] <= 180 and -90 <= c[1] <= 90) for c in req.coordinates):
        raise HTTPException(422, "coordonnées hors limites")
    return gpx.response(req.name, req.coordinates)


@app.get("/api/routes/{request_id}/progress")
def route_progress(request_id: str) -> dict:
    job = state.get("jobs", {}).get(request_id)
    if job is None:
        raise HTTPException(404, "génération inconnue ou terminée")
    return job.progress()


@app.post("/api/routes/{request_id}/cancel")
def cancel_route(request_id: str) -> dict:
    state.setdefault("jobs", {}).setdefault(request_id, Job()).cancel()
    return {"cancelled": True}


def _ascent_range(req: RouteRequest) -> tuple[float, float] | None:
    if req.ascent_min_m is None and req.ascent_max_m is None:
        return None
    lo = req.ascent_min_m or 0.0
    hi = req.ascent_max_m if req.ascent_max_m is not None else 10_000.0
    if hi < lo:
        raise HTTPException(422, "D+ max inférieur au D+ min")
    return lo, hi


# Production front: registered last so that every /api route above wins.
@app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)  # HEAD: `curl -I` checks
def frontend(path: str) -> FileResponse:
    """Files of the built front, and index.html for any other page so the front handles its own routes."""
    if path == "api" or path.startswith("api/"):
        raise HTTPException(404, "Not Found")
    root = FRONTEND_DIST.resolve()
    if not (root / "index.html").is_file():
        raise HTTPException(404, "front non construit (cd frontend && npm run build), ou utiliser Vite en dev")
    file = (root / path).resolve()
    if path and file.is_relative_to(root) and file.is_file():
        # Vite fingerprints everything under assets/: it never changes under the same name.
        immutable = file.is_relative_to(root / "assets")
        return FileResponse(file, headers={"Cache-Control": "public, max-age=31536000, immutable" if immutable else "no-cache"})
    return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})
