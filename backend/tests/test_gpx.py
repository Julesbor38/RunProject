import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app import api, gpx

from test_pipeline import make_data

NS = {"g": "http://www.topografix.com/GPX/1/1"}
COORDS = [[4.80, 45.76, 170.04], [4.81, 45.77, 180.0], [4.82, 45.78, 175.5]]


def check_gpx(text: str, name: str, points: int) -> ET.Element:
    assert text.startswith('<?xml version="1.0" encoding="UTF-8"?>\n')
    root = ET.fromstring(text.encode("utf-8"))
    assert root.tag == "{http://www.topografix.com/GPX/1/1}gpx"
    assert root.get("version") == "1.1" and root.get("creator") == "Trail Map"
    trks = root.findall("g:trk", NS)
    assert len(trks) == 1 and trks[0].findtext("g:name", namespaces=NS) == name
    pts = trks[0].findall("g:trkseg/g:trkpt", NS)
    assert len(pts) == points
    assert all(p.get("lat") and p.get("lon") and p.find("g:ele", NS) is not None for p in pts)
    return root


def check_headers(r) -> None:
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/gpx+xml"
    disposition = r.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="') and disposition.endswith('.gpx"')
    filename = disposition.split('"')[1]
    assert filename.isascii() and " " not in filename and filename.count(".") == 1


def test_gpx_document_is_valid_gpx_1_1():
    text = gpx.to_gpx("Itinéraire <A> & co", COORDS, [("Départ", 4.80, 45.76)], datetime(2026, 10, 7, tzinfo=timezone.utc))
    root = check_gpx(text, "Itinéraire <A> & co", 3)
    assert root.findtext("g:metadata/g:time", namespaces=NS) == "2026-10-07T00:00:00Z"
    assert root.find("g:wpt", NS).findtext("g:name", namespaces=NS) == "Départ"
    assert list(root)[1].tag.endswith("wpt")  # schema order: metadata, wpt, trk
    first = root.find("g:trk/g:trkseg/g:trkpt", NS)
    assert (first.get("lat"), first.get("lon"), first.findtext("g:ele", namespaces=NS)) == ("45.760000", "4.800000", "170.0")


def test_gpx_filename_is_plain_ascii():
    assert gpx.filename("Trail Map itinéraire 10,0 km") == "trail-map-itineraire-10-0-km.gpx"
    assert gpx.filename("ÉÉ / ??") == "ee.gpx"
    assert gpx.filename("???") == "trail-map.gpx"


def test_post_gpx_of_a_proposed_route(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(api, "DATA_DIR", make_data(tmp_path))
    with TestClient(api.app) as client:
        r = client.post("/api/routes/gpx", json={"name": "Trail Map boucle 3,1 km", "coordinates": COORDS})
        check_headers(r)
        assert 'filename="trail-map-boucle-3-1-km.gpx"' in r.headers["content-disposition"]
        check_gpx(r.content.decode("utf-8"), "Trail Map boucle 3,1 km", 3)
        assert client.post("/api/routes/gpx", json={"coordinates": [[4.8, 45.7]]}).status_code == 422
        assert client.post("/api/routes/gpx", json={"coordinates": [[4.8, 95], [4.8, 45]]}).status_code == 422


def test_generated_routes_are_saved_and_served_as_gpx(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(api, "DATA_DIR", make_data(tmp_path))
    fake = {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "id": 0, "geometry": {"type": "LineString", "coordinates": COORDS}, "properties": {"distance_m": 3140}}],
    }
    with TestClient(api.app) as client:
        client.get("/api/activities")  # loads the user's workspace
        monkeypatch.setattr(api._workspaces["tester"].routing, "generate", lambda *a, **k: fake)
        props = client.post("/api/routes", json={"start": [4.8, 45.76], "distance_km": 3}).json()["features"][0]["properties"]
        assert props["name"] == "Trail Map boucle 3,1 km" and props["gpx_filename"] == "trail-map-boucle-3-1-km.gpx"
        r = client.get(f"/api/routes/{props['route_id']}/gpx")
        check_headers(r)
        check_gpx(r.text, "Trail Map boucle 3,1 km", 3)
        assert client.get(f"/api/routes/{'0' * 32}/gpx").status_code == 404
        assert client.get("/api/routes/..%2Fx/gpx").status_code in (404, 422)
