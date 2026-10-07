import math

import pytest

from app.pois.catalog import classify, min_zoom, score
from app.pois.extract import extract
from app.pois.store import Poi, PoiStore

# ~200 m squares around (45.0, 4.0)
D = 0.002
OSM = f"""<?xml version='1.0' encoding='UTF-8'?>
<osm version="0.6">
  <node id="1" lat="45.000" lon="4.000" version="1"><tag k="natural" v="peak"/><tag k="name" v="Mont Test"/><tag k="ele" v="1500"/></node>
  <node id="2" lat="45.001" lon="4.001" version="1"><tag k="tourism" v="viewpoint"/></node>
  <node id="3" lat="45.002" lon="4.002" version="1"><tag k="historic" v="castle"/><tag k="name" v="Château"/><tag k="wikidata" v="Q1"/><tag k="ref:mhs" v="PA001"/></node>
  <node id="4" lat="45.003" lon="4.003" version="1"><tag k="amenity" v="drinking_water"/></node>
  <node id="5" lat="45.004" lon="4.004" version="1"><tag k="amenity" v="bench"/></node>
  <node id="6" lat="45.005" lon="4.005" version="1"><tag k="leisure" v="park"/></node>
  <node id="7" lat="45.0105" lon="4.0105" version="1"><tag k="leisure" v="park"/><tag k="name" v="Parc du Lac"/></node>
  <node id="10" lat="45.010" lon="4.010" version="1"/>
  <node id="11" lat="45.010" lon="{4.010 + D}" version="1"/>
  <node id="12" lat="{45.010 + D}" lon="{4.010 + D}" version="1"/>
  <node id="13" lat="{45.010 + D}" lon="4.010" version="1"/>
  <way id="100" version="1"><nd ref="10"/><nd ref="11"/><nd ref="12"/><nd ref="13"/><nd ref="10"/>
    <tag k="leisure" v="park"/><tag k="name" v="Parc du Lac"/></way>
  <node id="20" lat="45.020" lon="4.020" version="1"/>
  <node id="21" lat="45.020" lon="{4.020 + D}" version="1"/>
  <node id="22" lat="{45.020 + D}" lon="{4.020 + D}" version="1"/>
  <node id="23" lat="{45.020 + D}" lon="4.020" version="1"/>
  <way id="200" version="1"><nd ref="20"/><nd ref="21"/><nd ref="22"/><nd ref="23"/><nd ref="20"/></way>
  <relation id="300" version="1"><member type="way" ref="200" role="outer"/>
    <tag k="type" v="multipolygon"/><tag k="natural" v="water"/><tag k="name" v="Lac Bleu"/></relation>
  <node id="30" lat="45.030" lon="4.030" version="1"/>
  <node id="31" lat="45.031" lon="4.031" version="1"/>
  <node id="32" lat="45.032" lon="4.032" version="1"/>
  <way id="400" version="1"><nd ref="30"/><nd ref="31"/><tag k="waterway" v="river"/><tag k="name" v="La Rivière"/></way>
  <way id="401" version="1"><nd ref="31"/><nd ref="32"/><tag k="waterway" v="river"/><tag k="name" v="La Rivière"/></way>
  <way id="402" version="1"><nd ref="31"/><nd ref="32"/><tag k="waterway" v="stream"/></way>
</osm>
"""


@pytest.fixture
def store(tmp_path):
    (tmp_path / "x.osm").write_text(OSM)
    s = PoiStore(tmp_path / "pois.sqlite")
    extract(tmp_path / "x.osm", s)
    return s


def test_extraction_and_categories(store):
    by_id = {p.id: p for p in store.in_bbox((3.9, 44.9, 4.1, 45.1), limit=100)}
    kinds = {k: (p.category, p.kind) for k, p in by_id.items()}
    assert kinds["n1"] == ("nature", "peak")
    assert kinds["n2"] == ("nature", "viewpoint")  # unnamed viewpoints are kept
    assert kinds["n3"] == ("heritage", "castle")
    assert kinds["n4"] == ("utility", "drinking_water")
    assert "n5" not in by_id and "n6" not in by_id  # a bench; a nameless park
    assert kinds["r300"] == ("water", "lake")  # multipolygon -> its centre
    lake = by_id["r300"]
    assert lake.lat == pytest.approx(45.021, abs=1e-4) and lake.lon == pytest.approx(4.021, abs=1e-4)
    assert lake.radius_m == pytest.approx(math.sqrt(222 * 157 / math.pi), rel=0.05)  # ~222 x 157 m
    assert sum(1 for p in by_id.values() if p.name == "La Rivière") == 1  # one point per river and cell
    assert not any(p.kind == "stream" for p in by_id.values())  # nameless stream
    assert by_id["n3"].tags["ref:mhs"] == "PA001" and "bench" not in str(by_id["n3"].tags)


def test_node_and_surface_of_the_same_place_kept_once(store):
    parks = [p for p in store.in_bbox((3.9, 44.9, 4.1, 45.1), limit=100) if p.name == "Parc du Lac"]
    assert len(parks) == 1 and parks[0].id == "w100"  # the surface scores higher (its size)


def test_score_and_zoom():
    castle = score({"name": "C", "wikidata": "Q1", "ref:mhs": "PA1", "historic": "castle"}, "castle")
    cross = score({"historic": "wayside_cross"}, "cross")
    peak_high = score({"name": "P", "ele": "3000"}, "peak")
    peak_low = score({"name": "P", "ele": "300"}, "peak")
    assert castle > peak_high > peak_low > cross
    assert min_zoom(castle) < min_zoom(cross)
    big_lake = score({"name": "L"}, "lake", 5_000_000)
    pond = score({"name": "L"}, "lake", 2_000)
    assert big_lake > pond
    assert classify({"amenity": "place_of_worship"}) is None  # not heritage
    assert classify({"amenity": "place_of_worship", "heritage": "2", "name": "Église"}) == ("heritage", "church")
    assert classify({"natural": "water", "water": "wastewater", "name": "X"}) is None
    assert classify({"amenity": "toilets", "access": "private"}) is None


def test_bbox_zoom_and_category_filters(store):
    box = (3.9, 44.9, 4.1, 45.1)
    assert all(p.category == "water" for p in store.in_bbox(box, categories=["water"]))
    assert store.in_bbox(box, categories=[]) == []
    far = store.in_bbox(box, zoom=9)
    near = store.in_bbox(box, zoom=16)
    assert len(far) < len(near) and all(p.min_zoom <= 9 for p in far)
    best = store.in_bbox(box, limit=1)
    assert best[0].id == "n3"  # castle with Wikidata and ref:mhs


def test_places_along_a_route(tmp_path):
    s = PoiStore(tmp_path / "p.sqlite")
    k = 111_320 * math.cos(math.radians(45))
    s.add([
        Poi("near", 45.0 + 30 / 111_320, 4.005, "nature", "viewpoint", "Vue", 30, 12),  # 30 m north of the line
        Poi("far", 45.0 + 120 / 111_320, 4.005, "nature", "peak", "Pic", 40, 12),  # 120 m
        Poi("park", 45.0 + 300 / 111_320, 4.005, "park", "park", "Parc", 20, 13, radius_m=280),  # its edge ~20 m away
        Poi("on", 45.0, 4.0 + 300 / k, "water", "lake", "Lac", 20, 13),  # right on the line, 300 m along it
    ])
    line = [[4.0, 45.0], [4.0 + 1000 / k, 45.0]]  # 1 km due east
    found = {p.id for p in s.along(line, within_m=50)}
    assert found == {"near", "park", "on"}


# --- Wikidata (network faked) ---

import httpx  # noqa: E402

from app.pois import wikidata as wd  # noqa: E402
from app.pois.overpass import parse  # noqa: E402

ENTITIES = {
    "Q1": {
        "descriptions": {"fr": {"value": "château fort en France"}},
        "sitelinks": {"frwiki": {"title": "Château de Test"}},
        "claims": {"P18": [{"mainsnak": {"datavalue": {"value": "Chateau test.jpg"}}}]},
    },
    "Q2": {"descriptions": {}, "sitelinks": {}, "claims": {}},
}


def fake_wikimedia(calls):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if "wikidata" in request.url.host:
            ids = request.url.params["ids"].split("|")
            return httpx.Response(200, json={"entities": {i: ENTITIES.get(i, {}) for i in ids}})
        return httpx.Response(200, json={"query": {"pages": {"1": {
            "title": "File:Chateau test.jpg",
            "imageinfo": [{"thumburl": "https://upload.wikimedia.org/thumb.jpg", "descriptionurl": "https://commons.wikimedia.org/wiki/File:Chateau_test.jpg",
                           "extmetadata": {"Artist": {"value": '<a href="x">Jean &amp; Co</a>'}, "LicenseShortName": {"value": "CC BY-SA 4.0"},
                                           "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0"}}}],
        }}}})
    return httpx.Client(transport=httpx.MockTransport(handler), headers={"User-Agent": wd.USER_AGENT})


def test_wikidata_grouped_cached_and_credited(tmp_path, monkeypatch):
    calls = []
    w = wd.Wikidata(PoiStore(tmp_path / "p.sqlite"), fake_wikimedia(calls))
    w.fetch(["Q1", "Q2"])  # one grouped request (+ one for the pictures)
    assert len(calls) == 2 and calls[0].url.params["ids"] == "Q1|Q2"
    assert all("RunProject" in c.headers["user-agent"] for c in calls)
    d = w.get("Q1")
    assert d["description"] == "château fort en France"
    assert d["wikipedia"] == "https://fr.wikipedia.org/wiki/Château_de_Test"
    assert d["image"] == {"thumb": "https://upload.wikimedia.org/thumb.jpg", "page": "https://commons.wikimedia.org/wiki/File:Chateau_test.jpg",
                          "author": "Jean & Co", "license": "CC BY-SA 4.0", "license_url": "https://creativecommons.org/licenses/by-sa/4.0"}
    assert w.get("Q2") is None  # nothing useful: cached as empty
    assert len(calls) == 2  # from the cache, no new request
    later = __import__("time").time() + wd.TTL_S + 10
    monkeypatch.setattr(wd.time, "time", lambda: later)
    w.get("Q1")
    assert len(calls) == 4  # expired after 30 days: asked again
    assert w.get("not a qid") is None


def test_wikidata_failure_is_not_retried_at_once(tmp_path):
    calls = []

    def down(request):
        calls.append(request)
        return httpx.Response(503)

    w = wd.Wikidata(PoiStore(tmp_path / "p.sqlite"), httpx.Client(transport=httpx.MockTransport(down)))
    assert w.get("Q5") is None and w.get("Q5") is None
    assert len(calls) == 1  # failed: not asked again for a day


def test_overpass_elements_to_places():
    elements = [
        {"type": "node", "id": 1, "lat": 46.0, "lon": 7.0, "tags": {"natural": "peak", "name": "Dent", "ele": "3000"}},
        {"type": "way", "id": 2, "center": {"lat": 46.01, "lon": 7.01}, "bounds": {"minlat": 46.0, "minlon": 7.0, "maxlat": 46.02, "maxlon": 7.02},
         "tags": {"natural": "water", "name": "Lac"}},
        {"type": "way", "id": 3, "center": {"lat": 46.0, "lon": 7.0}, "tags": {"waterway": "river", "name": "Rhône"}},
        {"type": "way", "id": 4, "center": {"lat": 46.001, "lon": 7.001}, "tags": {"waterway": "river", "name": "Rhône"}},
        {"type": "node", "id": 5, "lat": 46.0, "lon": 7.0, "tags": {"amenity": "bench"}},
    ]
    places = {p.id: p for p in parse(elements)}
    assert set(places) == {"n1", "w2", "w3"}  # one point for the river in its cell, no bench
    assert places["w2"].radius_m > 500 and places["w2"].source == "overpass"


# --- API ---

from fastapi.testclient import TestClient  # noqa: E402

from app import api  # noqa: E402
from test_pipeline import make_data  # noqa: E402


def test_api_pois_and_sheet(tmp_path, monkeypatch):
    root = make_data(tmp_path)
    monkeypatch.setattr(api, "DATA_DIR", root)
    s = api.pois_store()
    s.add([
        Poi("n3", 45.002, 4.002, "heritage", "castle", "Château", 80, 9, {"name": "Château", "wikidata": "Q1", "ref:mhs": "PA001"}),
        Poi("n4", 45.003, 4.003, "utility", "drinking_water", "", 12, 14, {"amenity": "drinking_water"}),
    ])
    calls = []
    api._pois["wikidata"].client = fake_wikimedia(calls)
    with TestClient(api.app) as client:
        r = client.get("/api/pois", params={"bbox": "3.9,44.9,4.1,45.1", "zoom": 10})
        assert [f["id"] for f in r.json()["features"]] == ["n3"]  # the drinking water shows from zoom 14
        r = client.get("/api/pois", params={"bbox": "3.9,44.9,4.1,45.1", "zoom": 15, "categories": "utility"})
        assert [f["properties"]["kind"] for f in r.json()["features"]] == ["drinking_water"]
        assert client.get("/api/pois", params={"bbox": "3.9,44.9,4.1,45.1", "categories": ""}).json()["features"] == []
        assert client.get("/api/pois", params={"bbox": "nope"}).status_code == 422
        assert client.get("/api/pois", params={"bbox": "-10,-10,10,10"}).status_code == 422  # too large
        sheet = client.get("/api/pois/n3").json()
        assert sheet["mhs"] == "PA001" and sheet["osm_url"] == "https://www.openstreetmap.org/node/3"
        assert sheet["image"]["license"] == "CC BY-SA 4.0" and sheet["wikipedia"].endswith("Château_de_Test")
        assert client.get("/api/pois/n999").status_code == 404
        assert client.get("/api/pois/x1").status_code == 422


def test_routes_list_the_places_along_them(tmp_path, monkeypatch):
    root = make_data(tmp_path)
    monkeypatch.setattr(api, "DATA_DIR", root)
    api.pois_store().add([Poi("n7", 45.0003, 4.005, "nature", "viewpoint", "Belvédère", 30, 12)])
    fake = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": 0, "geometry": {"type": "LineString", "coordinates": [[4.0, 45.0], [4.01, 45.0]]}, "properties": {"distance_m": 790}}
    ]}
    with TestClient(api.app) as client:
        client.get("/api/activities")
        monkeypatch.setattr(api._workspaces["tester"].routing, "generate", lambda *a, **k: fake)
        props = client.post("/api/routes", json={"start": [4.0, 45.0], "distance_km": 1}).json()["features"][0]["properties"]
    assert props["pois"] == [{"id": "n7", "name": "Belvédère", "category": "nature", "kind": "viewpoint"}]
