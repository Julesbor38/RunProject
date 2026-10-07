from pathlib import Path

from fastapi.testclient import TestClient

from app import api
from app.ingest.pipeline import ingest

GPX = """<?xml version="1.0"?>
<gpx version="1.1" creator="t" xmlns="http://www.topografix.com/GPX/1/1"><trk><type>running</type><trkseg>
{pts}
</trkseg></trk></gpx>"""


def write_gpx(path: Path, lat0: float, hour: int = 13) -> None:
    pts = "\n".join(
        f'<trkpt lat="{lat0 + i * 0.001}" lon="4.65"><time>2026-10-03T{hour}:{i:02d}:00Z</time></trkpt>' for i in range(20)
    )
    path.write_text(GPX.format(pts=pts))


def make_data(root: Path) -> Path:
    raw = root / "raw"
    (raw / "strava" / "activities").mkdir(parents=True)
    write_gpx(raw / "strava" / "activities" / "1.gpx", 45.0)
    (raw / "strava" / "activities.csv").write_text(
        "Activity ID,Activity Name,Activity Type,Filename\n1,Sortie,Run,activities/1.gpx\n"
    )
    write_gpx(raw / "coros.gpx", 46.0, hour=17)
    return root


def test_ingest_folder_reads_nested_strava_archive_once(tmp_path: Path):
    res = ingest([make_data(tmp_path) / "raw"])
    assert sorted(a.source.startswith("strava:") for a in res.activities) == [False, True]
    assert res.duplicates == 0 and not res.errors


def test_api_serves_masked_geojson(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(api, "DATA_DIR", make_data(tmp_path))
    with TestClient(api.app) as client:
        fc = client.get("/api/activities").json()
    assert fc["stats"]["activities"] == 2
    geom = fc["features"][0]["geometry"]  # sorted by start: the Strava one
    assert geom["type"] == "MultiLineString"
    # 200 m trimmed at each end of a ~2.1 km straight line: first visible point is not the start
    assert geom["coordinates"][0][0][1] > 45.0015


def test_api_routes_validation_and_errors(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(api, "DATA_DIR", make_data(tmp_path))
    with TestClient(api.app) as client:
        assert client.post("/api/routes", json={"start": [4.65, 45.0]}).status_code == 422  # loop without distance
        bad = {"start": [4.65, 45.0], "distance_km": 5, "preferences": {"nature": 2}}
        assert client.post("/api/routes", json=bad).status_code == 422


def test_api_health(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(api, "DATA_DIR", make_data(tmp_path))
    monkeypatch.setattr(api, "FRONTEND_DIST", tmp_path / "no-dist")
    with TestClient(api.app) as client:
        health = client.get("/api/health").json()
    assert health["status"] == "ok" and health["activities"] == 2
    assert {"tiles_total", "tiles_cached", "running", "jobs_running"} <= health["routing"].keys()
    assert health["frontend"] is False


def test_api_serves_built_front_with_spa_fallback(tmp_path: Path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "assets" / "main-abc.js").write_text("console.log(1)")
    (tmp_path / "secret.txt").write_text("nope")
    monkeypatch.setattr(api, "DATA_DIR", make_data(tmp_path))
    monkeypatch.setattr(api, "FRONTEND_DIST", dist)
    with TestClient(api.app) as client:
        assert client.get("/").text == "<html>app</html>"
        assert client.head("/").status_code == 200
        asset = client.get("/assets/main-abc.js")
        assert asset.text == "console.log(1)" and "immutable" in asset.headers["cache-control"]
        assert client.get("/itineraire/42").text == "<html>app</html>"  # front route
        assert client.get("/..%2Fsecret.txt").text == "<html>app</html>"  # no escape from dist
        assert client.get("/api/nope").status_code == 404  # unknown API path: never index.html
        assert client.get("/api/health").json()["frontend"] is True


def test_api_without_built_front_serves_only_the_api(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(api, "DATA_DIR", make_data(tmp_path))
    monkeypatch.setattr(api, "FRONTEND_DIST", tmp_path / "no-dist")
    with TestClient(api.app) as client:
        assert client.get("/").status_code == 404
        assert client.get("/api/activities").status_code == 200
