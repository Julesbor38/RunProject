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
