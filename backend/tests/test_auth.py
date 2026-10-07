import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import api, auth

from test_pipeline import make_data

pytestmark = pytest.mark.auth


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    data = make_data(tmp_path)
    monkeypatch.setattr(api, "DATA_DIR", data)
    monkeypatch.setattr(auth, "SCRYPT", {"n": 2**10, "r": 8, "p": 1})  # fast hashes in tests
    monkeypatch.setattr(auth, "_failures", {})
    auth.set_password(data, "jules", "correct horse battery")
    # https: the session cookie is Secure
    with TestClient(api.app, base_url="https://testserver") as c:
        yield c


def test_api_needs_a_session(client):
    assert client.get("/api/activities").status_code == 401
    assert client.get("/api/routes/" + "0" * 32 + "/gpx").status_code == 401
    assert client.post("/api/reload").status_code == 401
    assert client.get("/api/nope").status_code == 401  # unknown routes too: nothing to probe
    assert client.get("/api/health").status_code == 200  # public, no track data


def test_login_logout(client):
    assert client.post("/api/auth/login", json={"username": "jules", "password": "wrong password!"}).status_code == 401
    r = client.post("/api/auth/login", json={"username": "jules", "password": "correct horse battery"})
    assert r.status_code == 200
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
    assert client.get("/api/auth/me").json() == {"user": "jules"}
    assert client.get("/api/activities").status_code == 200
    client.post("/api/auth/logout")
    assert client.get("/api/activities").status_code == 401


def test_secrets_are_not_stored_in_clear(client, tmp_path):
    token = client.post("/api/auth/login", json={"username": "jules", "password": "correct horse battery"}).cookies[auth.COOKIE]
    files = (api.DATA_DIR / "auth").glob("*.json")
    text = "".join(f.read_text() for f in files)
    assert "correct horse battery" not in text and token not in text
    assert oct((api.DATA_DIR / "auth" / "users.json").stat().st_mode)[-3:] == "600"


def test_unknown_user_and_lockout(client):
    assert client.post("/api/auth/login", json={"username": "nobody", "password": "x"}).status_code == 401
    for _ in range(auth.MAX_FAILURES):
        client.post("/api/auth/login", json={"username": "jules", "password": "nope"})
    # locked, even with the right password
    assert client.post("/api/auth/login", json={"username": "jules", "password": "correct horse battery"}).status_code == 429


def test_new_password_ends_sessions_and_short_passwords_are_refused(client):
    client.post("/api/auth/login", json={"username": "jules", "password": "correct horse battery"})
    auth.set_password(api.DATA_DIR, "jules", "another long password")
    assert client.get("/api/activities").status_code == 401
    with pytest.raises(ValueError):
        auth.set_password(api.DATA_DIR, "jules", "short")


def test_removed_user_is_logged_out(client):
    client.post("/api/auth/login", json={"username": "jules", "password": "correct horse battery"})
    assert auth.remove_user(api.DATA_DIR, "jules")
    assert client.get("/api/activities").status_code == 401
    assert json.loads((api.DATA_DIR / "auth" / "users.json").read_text()) == {}
