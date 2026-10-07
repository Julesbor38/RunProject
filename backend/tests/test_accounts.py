"""Sign-up from the page, and each account seeing only its own data."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import api, auth
from app.workspace import adopt_legacy

from test_pipeline import make_data, user_data, write_gpx

pytestmark = pytest.mark.auth


@pytest.fixture
def data(tmp_path: Path, monkeypatch):
    root = make_data(tmp_path)  # "tester" owns 2 activities
    monkeypatch.setattr(api, "DATA_DIR", root)
    monkeypatch.setattr(auth, "SCRYPT", {"n": 2**10, "r": 8, "p": 1})
    monkeypatch.setattr(auth, "_failures", {})
    monkeypatch.setattr(auth, "_signups", {})
    auth.set_password(root, "tester", "tester password")
    return root


def client():
    return TestClient(api.app, base_url="https://testserver")


def test_signup_creates_an_empty_account_and_logs_in(data):
    with client() as c:
        r = c.post("/api/auth/signup", json={"username": " Marie ", "password": "long enough pw"})
        assert r.status_code == 200 and r.json() == {"user": "marie"}
        assert c.get("/api/auth/me").json() == {"user": "marie"}
        assert c.get("/api/activities").json()["stats"]["activities"] == 0  # not tester's runs
        assert c.get("/api/auth/options").json() == {"signup": True}
    assert (data / "users" / "marie" / "raw").is_dir()


def test_signup_rules(data, monkeypatch):
    with client() as c:
        def signup(name, pw="long enough pw"):
            return c.post("/api/auth/signup", json={"username": name, "password": pw})

        assert "déjà pris" in signup("TESTER").json()["detail"]
        assert signup("ab").status_code == 422  # too short
        assert signup("../etc").status_code == 422  # also a folder name: no path tricks
        assert signup("paul", "short").status_code == 422
        for i in range(auth.MAX_SIGNUPS):
            signup(f"user{i}")
        assert signup("onemore").status_code == 429
        monkeypatch.setattr(auth, "SIGNUP_OPEN", False)
        assert signup("closed").status_code == 403


def test_each_account_only_sees_its_own_data(data):
    with client() as a, client() as b:
        a.post("/api/auth/login", json={"username": "tester", "password": "tester password"})
        b.post("/api/auth/signup", json={"username": "marie", "password": "long enough pw"})
        tester_runs = a.get("/api/activities").json()
        assert tester_runs["stats"]["activities"] == 2 and b.get("/api/activities").json()["features"] == []
        key = tester_runs["features"][0]["properties"]["key"]
        assert a.put(f"/api/ratings/{key}", json={"scores": {"safety": 5}}).status_code == 200
        assert b.get("/api/ratings").json()["ratings"] == {}
        assert b.put(f"/api/ratings/{key}", json={"scores": {"safety": 1}}).status_code == 404  # not her run
        # a file uploaded by marie stays hers
        gpx = data / "x.gpx"
        write_gpx(gpx, 47.0, hour=6)
        assert b.post("/api/import", files=[("files", ("matin.gpx", gpx.read_bytes(), "application/gpx+xml"))]).status_code == 200
        for _ in range(100):
            if b.get("/api/import/status").json()["state"] != "running":
                break
        assert b.get("/api/activities").json()["stats"]["activities"] == 1
        assert a.get("/api/activities").json()["stats"]["activities"] == 2
        assert (user_data(data, "marie") / "raw" / "uploads" / "matin.gpx").exists()


def test_routes_gpx_are_private(data, monkeypatch):
    with client() as a, client() as b:
        a.post("/api/auth/login", json={"username": "tester", "password": "tester password"})
        b.post("/api/auth/signup", json={"username": "marie", "password": "long enough pw"})
        a.get("/api/activities")
        fake = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "id": 0, "geometry": {"type": "LineString", "coordinates": [[4.8, 45.7], [4.81, 45.71]]}, "properties": {"distance_m": 1500}}
        ]}
        monkeypatch.setattr(api._workspaces["tester"].routing, "generate", lambda *x, **k: fake)
        route_id = a.post("/api/routes", json={"start": [4.8, 45.7], "distance_km": 2}).json()["features"][0]["properties"]["route_id"]
        assert a.get(f"/api/routes/{route_id}/gpx").status_code == 200
        assert b.get(f"/api/routes/{route_id}/gpx").status_code == 404


def test_adopt_legacy_data(tmp_path):
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "a.fit").write_bytes(b"x")
    (tmp_path / "ratings.json").write_text("{}")
    (tmp_path / "users" / "jules" / "raw").mkdir(parents=True)  # empty: created by a first login
    assert adopt_legacy(tmp_path, "jules") == ["raw", "ratings.json"]
    assert (tmp_path / "users" / "jules" / "raw" / "a.fit").exists() and not (tmp_path / "raw").exists()
    (tmp_path / "ratings.json").write_text("{}")
    with pytest.raises(FileExistsError):
        adopt_legacy(tmp_path, "jules")  # never overwrites


def _route(client_, monkeypatch, user):
    """Generate (fake) one route for the logged-in user and return its id."""
    client_.get("/api/activities")
    fake = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": 0, "geometry": {"type": "LineString", "coordinates": [[4.8, 45.7, 200.0], [4.81, 45.71, 210.0]]}, "properties": {"distance_m": 1500}}
    ]}
    monkeypatch.setattr(api._workspaces[user].routing, "generate", lambda *x, **k: fake)
    return client_.post("/api/routes", json={"start": [4.8, 45.7], "distance_km": 2}).json()["features"][0]["properties"]["route_id"]


def test_dl_link_headers_and_scope(data, monkeypatch):
    with client() as a:
        a.post("/api/auth/login", json={"username": "tester", "password": "tester password"})
        route_id = _route(a, monkeypatch, "tester")
        link = a.post(f"/api/routes/{route_id}/link").json()["url"]
        assert link.startswith(f"/dl/{route_id}.gpx?")  # outside the PWA scope (/app/)
        assert a.post(f"/api/routes/{'0' * 32}/link").status_code == 404
    with client() as window:  # no session: an out-of-scope window may not carry the app's cookies
        r = window.get(link)
        assert r.status_code == 200 and r.headers["content-type"] == "application/gpx+xml"
        assert r.headers["content-disposition"] == 'attachment; filename="trail-map-boucle-1-5-km.gpx"'
        assert "<trkpt" in r.text and "<ele>" in r.text
        assert window.get("/api/activities").status_code == 401  # only that file is open


def test_dl_link_expires(data, monkeypatch):
    with client() as a:
        a.post("/api/auth/login", json={"username": "tester", "password": "tester password"})
        link = a.post(f"/api/routes/{_route(a, monkeypatch, 'tester')}/link").json()["url"]
        monkeypatch.setattr(api.time, "time", lambda: 4_000_000_000)
        assert a.get(link).status_code == 403
        assert "expiré" in a.get(link).json()["detail"]


def test_dl_link_refused_for_another_user(data, monkeypatch):
    with client() as a, client() as b:
        a.post("/api/auth/login", json={"username": "tester", "password": "tester password"})
        b.post("/api/auth/signup", json={"username": "marie", "password": "long enough pw"})
        tester_route = _route(a, monkeypatch, "tester")
        marie_route = _route(b, monkeypatch, "marie")
        link = a.post(f"/api/routes/{tester_route}/link").json()["url"]
        assert b.post(f"/api/routes/{tester_route}/link").status_code == 404  # not her route
        assert b.get(link.replace("user=tester", "user=marie")).status_code == 403  # the link is bound to its account
        assert b.get(link.replace(tester_route, marie_route)).status_code == 403  # and to its route
        assert b.get(link.replace("sig=", "sig=0")).status_code == 403  # tampered
        assert b.get(link.replace("user=tester", "user=../tester")).status_code == 403


def test_native_app_session_token(data):
    """The native app (capacitor://localhost) can't use the cookie: it sends the token as a Bearer header."""
    with client() as app_:
        r = app_.post("/api/auth/login", json={"username": "tester", "password": "tester password", "token": True})
        token = r.json()["token"]
        assert r.json()["user"] == "tester" and len(token) > 30
    with client() as native:  # no cookie at all
        assert native.get("/api/activities").status_code == 401
        bearer = {"Authorization": f"Bearer {token}"}
        assert native.get("/api/auth/me", headers=bearer).json() == {"user": "tester"}
        assert native.get("/api/activities", headers=bearer).json()["stats"]["activities"] == 2
        assert native.get("/api/activities", headers={"Authorization": "Bearer nope"}).status_code == 401
        native.post("/api/auth/logout", headers=bearer)
        assert native.get("/api/activities", headers=bearer).status_code == 401
    with client() as web:  # without the flag, no token in the answer (the web app uses the cookie)
        assert "token" not in web.post("/api/auth/login", json={"username": "tester", "password": "tester password"}).json()


def test_cors_only_for_the_native_app(data):
    with client() as c:
        native = {"Origin": "capacitor://localhost"}
        pre = c.options("/api/activities", headers={**native, "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"})
        assert pre.status_code == 200 and pre.headers["access-control-allow-origin"] == "capacitor://localhost"
        assert "authorization" in pre.headers["access-control-allow-headers"].lower()
        refused = c.get("/api/activities", headers=native)  # a 401 the app can read
        assert refused.status_code == 401 and refused.headers["access-control-allow-origin"] == "capacitor://localhost"
        other = c.options("/api/activities", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
        assert "access-control-allow-origin" not in other.headers
        assert "access-control-allow-origin" not in c.get("/api/health", headers={"Origin": "https://evil.example"}).headers
