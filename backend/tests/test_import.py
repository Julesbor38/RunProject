import io
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import api, imports

from test_pipeline import make_data, user_data, write_gpx


def strava_zip(tmp_path: Path, n: int, extra: dict[str, bytes] | None = None) -> bytes:
    """A Strava export with `n` runs (ids 1..n), as Strava builds it (plus unrelated files)."""
    src = tmp_path / "zipsrc"
    (src / "activities").mkdir(parents=True, exist_ok=True)
    rows = ["Activity ID,Activity Name,Activity Type,Filename"]
    for i in range(1, n + 1):
        write_gpx(src / "activities" / f"{i}.gpx", 45.0 + i * 0.1, hour=10 + i)
        rows.append(f"{i},Sortie {i},Run,activities/{i}.gpx")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("activities.csv", "\n".join(rows) + "\n")
        for i in range(1, n + 1):
            zf.write(src / "activities" / f"{i}.gpx", f"activities/{i}.gpx")
        zf.writestr("media/photo.jpg", b"jpg")
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return buf.getvalue()


def wait_import(client) -> dict:
    for _ in range(200):
        s = client.get("/api/import/status").json()
        if s["state"] != "running":
            return s
        time.sleep(0.05)
    raise AssertionError("import still running")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "DATA_DIR", make_data(tmp_path))
    with TestClient(api.app) as c:
        yield c


def test_new_strava_export_adds_its_new_activities(client, tmp_path):
    assert client.get("/api/activities").json()["stats"]["activities"] == 2
    r = client.post("/api/import", files=[("files", ("export_123.zip", strava_zip(tmp_path, 3), "application/zip"))])
    assert r.status_code == 200, r.text
    s = wait_import(client)
    assert s["state"] == "done" and sorted(s["new"]) == ["strava:2", "strava:3"]  # strava:1 was already there
    assert client.get("/api/activities").json()["stats"]["activities"] == 4  # 3 Strava + the Coros file
    raw = user_data(api.DATA_DIR) / "raw"
    assert not (raw / "strava" / "media").exists()  # only what the import reads
    assert (raw / "strava-export.zip").exists() and not (raw / "strava.new").exists()


def test_single_files_are_added(client):
    gpx = (user_data(api.DATA_DIR) / "raw" / "coros.gpx").read_text().replace("46.0", "47.0").replace("T17:", "T08:")
    r = client.post("/api/import", files=[("files", ("../../ma sortie.gpx", gpx.encode(), "application/gpx+xml"))])
    assert r.status_code == 200
    assert wait_import(client)["new"] == ["file:ma_sortie.gpx"]
    assert (user_data(api.DATA_DIR) / "raw" / "uploads" / "ma_sortie.gpx").exists()  # no path from the client


def test_bad_uploads_are_refused(client, tmp_path):
    def post(name, data):
        return client.post("/api/import", files=[("files", (name, data, "application/octet-stream"))])

    assert post("notes.txt", b"hello").status_code == 422
    assert post("broken.zip", b"not a zip").status_code == 422
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("photos/a.jpg", b"x")
    assert "activities.csv" in post("other.zip", buf.getvalue()).json()["detail"]
    evil = strava_zip(tmp_path, 1, {"activities/../../../evil.gpx": b"<gpx/>"})
    assert post("evil.zip", evil).status_code == 422
    assert not (user_data(api.DATA_DIR) / "raw" / "strava.new").exists()  # nothing half-extracted left behind
    assert not (tmp_path / "evil.gpx").exists() and not (api.DATA_DIR / "evil.gpx").exists() and not (user_data(api.DATA_DIR) / "evil.gpx").exists()
    wait_import(client)


def test_zip_bomb_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(imports, "MAX_UNZIPPED", 1000)
    path = tmp_path / "big.zip"
    path.write_bytes(strava_zip(tmp_path, 3))
    with pytest.raises(imports.InvalidImport):
        imports.install_strava_zip(path, tmp_path / "raw")


def test_ratings(client):
    key = client.get("/api/activities").json()["features"][0]["properties"]["key"]
    assert key == "strava:1"
    crit = [c["key"] for c in client.get("/api/ratings").json()["criteria"]]
    assert {"safety", "lighting", "scenery"} <= set(crit)
    r = client.put(f"/api/ratings/{key}", json={"scores": {"safety": 4, "scenery": 5}, "comment": " Belle vue "})
    assert r.status_code == 200 and r.json()["comment"] == "Belle vue"
    assert client.get("/api/ratings").json()["ratings"][key]["scores"] == {"safety": 4, "scenery": 5}
    assert client.put(f"/api/ratings/{key}", json={"scores": {"safety": 6}}).status_code == 422
    assert client.put(f"/api/ratings/{key}", json={"scores": {"speed": 3}}).status_code == 422
    assert client.put("/api/ratings/strava:999", json={"scores": {"safety": 3}}).status_code == 404
    assert client.delete(f"/api/ratings/{key}").json() == {"deleted": True}
    assert client.get("/api/ratings").json()["ratings"] == {}
