"""HTTP API: serves each user's ingested activities as privacy-masked GeoJSON, routes, ratings.

No database yet: each account's activities are read from data/users/<name>/raw on its first request
(cached in its cache/) and kept in memory (`Workspace`). OSM tiles and elevation are shared.
Dev: uvicorn app.api:app --reload (the front is served by Vite on :5173).
Production: build the front (npm run build), then uvicorn app.api:app --host 127.0.0.1 --port 8000
serves both the API and frontend/dist on a single port (see SELF-HOST.md).
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Path as PathParam, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import gpx, imports, ratings
from . import auth
from .auth import COOKIE, SESSION_DAYS, session_user
from .ingest import load_zones, mask
from .ingest.models import TrackPoint
from .ingest.pipeline import ingest
from .ingest.privacy import DEFAULT_TRIM_M
from .ingest.simplify import simplify
from .routing import Preferences, RoutingError, RoutingService
from .routing.elevation import Dem
from .routing.job import Cancelled, Job
from .workspace import Workspace, user_dir

DATA_DIR = Path(os.environ.get("TRAILMAP_DATA", Path(__file__).parents[2] / "data"))
SIMPLIFY_TOLERANCE_M = 5.0
PREFETCH_OSM = os.environ.get("TRAILMAP_PREFETCH", "1") != "0"
# Generated routes kept for GET /api/routes/{route_id}/gpx (the newest ones only).
MAX_SAVED_ROUTES = 300
DL_LINK_TTL_S = 3600  # signed /dl/ links to a route's GPX
APP_PATH = "/app/"  # the front (and the PWA scope): /dl/ stays outside it, see shared_gpx
# Built front (npm run build); served by the API when present, so production needs a single port.
FRONTEND_DIST = Path(os.environ.get("TRAILMAP_FRONTEND_DIST", Path(__file__).parents[2] / "frontend" / "dist"))

state: dict = {}
_workspaces: dict[str, Workspace] = {}
_workspaces_lock = threading.Lock()
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


def activity_key(source: str) -> str:
    """Stable id of an activity across re-imports: its Strava id, else its file name."""
    return source if source.startswith("strava:") else "file:" + Path(source).name


def _with_keys(fc: dict) -> dict:
    for f in fc["features"]:
        f["properties"]["key"] = activity_key(f["properties"]["source"])
    return fc


def _lonlat(p: TrackPoint) -> list[float]:
    return [round(p.lon, 6), round(p.lat, 6)]


def load_cached(data_dir: Path, force: bool = False) -> dict:
    """Ingest is slow (~20 s for a full Strava export): reuse data/cache/ while inputs are unchanged."""
    cache = data_dir / "cache" / "activities.geojson"
    inputs = [p for p in (data_dir / "raw").rglob("*") if p.is_file()] + [data_dir / "privacy.json"]
    newest = max((p.stat().st_mtime for p in inputs if p.exists()), default=0)
    if not force and cache.exists() and cache.stat().st_mtime > newest:
        return _with_keys(json.loads(cache.read_text()))
    fc = build_feature_collection(data_dir)
    cache.parent.mkdir(exist_ok=True)
    cache.write_text(json.dumps(fc))
    return _with_keys(fc)


def routing_service(fc: dict) -> RoutingService:
    tracks = [line for f in fc["features"] for line in f["geometry"]["coordinates"]]
    return RoutingService(DATA_DIR / "osm", tracks, Dem(DATA_DIR / "dem"))


def workspace(request: Request) -> Workspace:
    """FastAPI dependency: the logged-in user's data, loaded on their first request."""
    user = request.state.user
    folder = user_dir(DATA_DIR, user)
    with _workspaces_lock:
        ws = _workspaces.get(user)
        if ws is None or ws.dir != folder:
            (folder / "raw").mkdir(parents=True, exist_ok=True)
            fc = load_cached(folder)
            ws = Workspace(user, folder, fc, routing_service(fc))
            if PREFETCH_OSM:
                ws.routing.start_prefetch()  # the user's running areas (abroad: Overpass)
            _workspaces[user] = ws
    return ws


@asynccontextmanager
async def lifespan(_: FastAPI):
    _workspaces.clear()
    state["started_at"] = time.time()
    yield


app = FastAPI(title="Trail Map", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["GET", "POST", "PUT", "DELETE"])

PUBLIC_API = {"/api/health", "/api/auth/login", "/api/auth/logout", "/api/auth/signup", "/api/auth/options"}


@app.middleware("http")
async def require_login(request: Request, call_next):
    """Every /api route needs a session, except the few public ones: new routes are protected by default."""
    path = request.url.path
    if (path == "/api" or path.startswith("/api/")) and path not in PUBLIC_API:
        user = session_user(DATA_DIR, request.cookies.get(COOKIE))
        if user is None:
            return JSONResponse({"detail": "connexion requise"}, status_code=401)
        request.state.user = user
    return await call_next(request)


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


def _client(request: Request) -> str:
    return request.client.host if request.client else "?"


def _set_session(response: Response, token: str) -> None:
    # Secure: sent over HTTPS (Tailscale) and http://localhost only, which browsers treat as secure.
    response.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True, secure=True, samesite="strict", path="/")


@app.post("/api/auth/login")
def login(body: LoginIn, request: Request, response: Response) -> dict:
    _set_session(response, auth.login(DATA_DIR, body.username, body.password, _client(request)))
    return {"user": auth.normalize(body.username)}


@app.get("/api/auth/options")
def auth_options() -> dict:
    return {"signup": auth.SIGNUP_OPEN}


@app.post("/api/auth/signup")
def signup(body: LoginIn, request: Request, response: Response) -> dict:
    """Create an account (its data starts empty) and log it in."""
    if not auth.SIGNUP_OPEN:
        raise HTTPException(403, "la création de compte est fermée sur ce serveur")
    try:
        name = auth.create_user(DATA_DIR, body.username, body.password, _client(request))
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    _set_session(response, auth.new_session(DATA_DIR, name))
    return {"user": name}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response) -> dict:
    auth.logout(DATA_DIR, request.cookies.get(COOKIE))
    response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="strict")
    return {"ok": True}


@app.get("/api/auth/me")
def me(request: Request) -> dict:
    return {"user": request.state.user}


@app.api_route("/api/health", methods=["GET", "HEAD"])
def health() -> dict:
    """Liveness (public: nothing about any user's data). Used by deploy-local.sh and monitoring."""
    return {
        "status": "ok",
        "uptime_s": round(time.time() - state["started_at"]),
        "accounts_loaded": len(_workspaces),
        "jobs_running": sum(len(ws.jobs) for ws in list(_workspaces.values())),
        "frontend": (FRONTEND_DIST / "index.html").is_file(),
    }


@app.get("/api/activities")
def activities(ws: Workspace = Depends(workspace)) -> dict:
    return ws.activities


@app.post("/api/reload")
def reload(ws: Workspace = Depends(workspace)) -> dict:
    _reload(ws)
    return ws.activities["stats"]


def _reload(ws: Workspace) -> None:
    activities = load_cached(ws.dir, force=True)
    ws.routing = routing_service(activities)
    ws.activities = activities


# --- adding activities: new Strava export or single files, imported in the background ---


@app.post("/api/import")
def import_files(files: list[UploadFile] = File(...), ws: Workspace = Depends(workspace)) -> dict:
    """Store the uploaded files, then re-import everything in the background (GET /api/import/status)."""
    if not ws.import_lock.acquire(blocking=False):
        raise HTTPException(409, "un import est déjà en cours")
    try:
        raw = ws.dir / "raw"
        with tempfile.TemporaryDirectory(dir=ws.dir) as tmp:
            added = 0
            for upload in files:
                name = upload.filename or "fichier"
                path = Path(tmp) / f"upload-{added}"
                imports.save_stream(upload.file, path)
                if name.lower().endswith(".zip"):
                    added += imports.install_strava_zip(path, raw)
                    shutil.copyfile(path, raw / "strava-export.zip")  # the latest full export, for backups
                else:
                    imports.install_file(path, name, raw)
                    added += 1
    except imports.InvalidImport as e:
        ws.import_lock.release()
        raise HTTPException(422, str(e)) from e
    except BaseException:
        ws.import_lock.release()
        raise
    before = {f["properties"]["key"] for f in ws.activities["features"]}
    ws.import_status = {"state": "running", "files": added, "started": time.time()}
    threading.Thread(target=_run_import, args=(ws, before), daemon=True).start()
    return ws.import_status


def _run_import(ws: Workspace, before: set[str]) -> None:
    try:
        _reload(ws)
        new = [f["properties"]["key"] for f in ws.activities["features"] if f["properties"]["key"] not in before]
        ws.import_status = {**ws.import_status, "state": "done", "new": new, "activities": ws.activities["stats"]["activities"]}
    except Exception as e:  # noqa: BLE001 - reported to the user
        logging.getLogger("app").exception("import failed")
        ws.import_status = {**ws.import_status, "state": "error", "message": str(e)}
    finally:
        ws.import_lock.release()


@app.get("/api/import/status")
def import_status(ws: Workspace = Depends(workspace)) -> dict:
    return ws.import_status


# --- ratings of the user's activities ---


@app.get("/api/ratings")
def get_ratings(ws: Workspace = Depends(workspace)) -> dict:
    return {
        "criteria": [{"key": k, "label": label} for k, label in ratings.CRITERIA],
        "ratings": ratings.for_user(ws.dir, ws.user),
    }


class RatingIn(BaseModel):
    scores: dict[str, int] = Field(default_factory=dict)
    comment: str = Field("", max_length=2000)


@app.put("/api/ratings/{key}")
def put_rating(key: str, body: RatingIn, ws: Workspace = Depends(workspace)) -> dict:
    if key not in {f["properties"]["key"] for f in ws.activities["features"]}:
        raise HTTPException(404, "sortie inconnue")
    if unknown := set(body.scores) - ratings.CRITERIA_KEYS:
        raise HTTPException(422, f"critères inconnus : {', '.join(sorted(unknown))}")
    if any(not 1 <= v <= 5 for v in body.scores.values()):
        raise HTTPException(422, "les notes vont de 1 à 5")
    if not body.scores and not body.comment.strip():
        raise HTTPException(422, "rien à enregistrer")
    return ratings.save(ws.dir, ws.user, key, body.scores, body.comment.strip())


@app.delete("/api/ratings/{key}")
def delete_rating(key: str, ws: Workspace = Depends(workspace)) -> dict:
    return {"deleted": ratings.delete(ws.dir, ws.user, key)}


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
    flat: bool = False  # the flattest routes (petals of small loops allowed), instead of a D+ range


@app.get("/api/routing/status")
def routing_status(ws: Workspace = Depends(workspace)) -> dict:
    """Progress of the background OSM download around the user's running areas."""
    return ws.routing.status()


@app.post("/api/routes")
def routes(req: RouteRequest, ws: Workspace = Depends(workspace)) -> dict:
    """Generate up to 3 loops (or one A-to-B route) matching the preferences."""
    jobs = ws.jobs
    # setdefault: a cancel that arrived before the request itself still applies.
    job = jobs.setdefault(req.request_id, Job()) if req.request_id else Job()
    try:
        out = ws.routing.generate(
            req.start,
            Preferences(**req.preferences.model_dump()),
            distance_m=req.distance_km * 1000 if req.distance_km else None,
            end=req.end,
            ascent_range=None if req.flat else _ascent_range(req),
            job=job,
            flat=req.flat,
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
        save_route(ws.dir, f, f"Trail Map {kind} {f['properties']['distance_m'] / 1000:.1f} km".replace(".", ","))
    return out


def save_route(user_folder: Path, feature: dict, name: str) -> None:
    """Keeps the route in the user's routes/ and gives it a `route_id`, a `name` and its GPX `gpx_filename`."""
    route_id = uuid.uuid4().hex
    feature["properties"].update(route_id=route_id, name=name, gpx_filename=gpx.filename(name))
    folder = user_folder / "routes"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{route_id}.json").write_text(json.dumps({"name": name, "coordinates": feature["geometry"]["coordinates"]}))
    saved = sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime)
    for old in saved[:-MAX_SAVED_ROUTES]:
        old.unlink(missing_ok=True)


@app.get("/api/routes/{route_id}/gpx")
def route_gpx(route_id: str = PathParam(pattern="^[0-9a-f]{32}$"), ws: Workspace = Depends(workspace)):
    """GPX of one of the user's generated routes, as a download (Safari on iOS: « Ouvrir dans… »)."""
    file = ws.dir / "routes" / f"{route_id}.json"
    if not file.is_file():
        raise HTTPException(404, "itinéraire inconnu ou expiré, régénérez-le")
    saved = json.loads(file.read_text())
    return gpx.response(saved["name"], saved["coordinates"])


@app.post("/api/routes/{route_id}/link")
def route_link(route_id: str = PathParam(pattern="^[0-9a-f]{32}$"), ws: Workspace = Depends(workspace)) -> dict:
    """A signed, expiring link to one of the user's routes as GPX, usable without the session (see shared_gpx)."""
    if not (ws.dir / "routes" / f"{route_id}.json").is_file():
        raise HTTPException(404, "itinéraire inconnu ou expiré, régénérez-le")
    expires = int(time.time()) + DL_LINK_TTL_S
    sig = auth.sign_link(DATA_DIR, "dl", ws.user, route_id, expires)
    return {"url": f"/dl/{route_id}.gpx?user={ws.user}&expires={expires}&sig={sig}", "expires": expires}


@app.get("/dl/{route_id}.gpx")
def shared_gpx(route_id: str = PathParam(pattern="^[0-9a-f]{32}$"), user: str = "", expires: int = 0, sig: str = ""):
    """GPX through a signed link, outside the PWA scope (APP_PATH): opened from the iOS home-screen app, iOS
    shows it in a window over the app (with its own « OK » / ✕), never in place of the app. Fallback only:
    the app shares the file itself when the system share sheet accepts it."""
    if not auth.USERNAME.match(user) or not auth.check_link(DATA_DIR, sig, expires, "dl", user, route_id):
        raise HTTPException(403, "lien expiré ou invalide : relancez « Envoyer vers la montre » depuis l'app")
    file = user_dir(DATA_DIR, user) / "routes" / f"{route_id}.json"
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
def route_progress(request_id: str, ws: Workspace = Depends(workspace)) -> dict:
    job = ws.jobs.get(request_id)
    if job is None:
        raise HTTPException(404, "génération inconnue ou terminée")
    return job.progress()


@app.post("/api/routes/{request_id}/cancel")
def cancel_route(request_id: str, ws: Workspace = Depends(workspace)) -> dict:
    ws.jobs.setdefault(request_id, Job()).cancel()
    return {"cancelled": True}


def _ascent_range(req: RouteRequest) -> tuple[float, float] | None:
    if req.ascent_min_m is None and req.ascent_max_m is None:
        return None
    lo = req.ascent_min_m or 0.0
    hi = req.ascent_max_m if req.ascent_max_m is not None else 10_000.0
    if hi < lo:
        raise HTTPException(422, "D+ max inférieur au D+ min")
    return lo, hi


# Production front, under APP_PATH: registered last so that every /api and /dl route above wins.
@app.api_route("/{path:path}", methods=["GET", "HEAD"], include_in_schema=False)  # HEAD: `curl -I` checks
def frontend(path: str):
    """Files of the built front under /app/, and its index.html for any other page there; / goes to /app/
    (also for home-screen apps installed when the front was at the root)."""
    if path == "api" or path.startswith("api/"):
        raise HTTPException(404, "Not Found")
    prefix = APP_PATH.strip("/")
    if path != prefix and not path.startswith(prefix + "/"):
        if path in ("", "index.html"):
            return RedirectResponse(APP_PATH)
        raise HTTPException(404, "Not Found")
    root = FRONTEND_DIST.resolve()
    if not (root / "index.html").is_file():
        raise HTTPException(404, "front non construit (cd frontend && npm run build), ou utiliser Vite en dev")
    rel = path[len(prefix) + 1 :]
    file = (root / rel).resolve()
    if rel and file.is_relative_to(root) and file.is_file():
        # Vite fingerprints everything under assets/: it never changes under the same name.
        immutable = file.is_relative_to(root / "assets")
        return FileResponse(file, headers={"Cache-Control": "public, max-age=31536000, immutable" if immutable else "no-cache"})
    return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})
