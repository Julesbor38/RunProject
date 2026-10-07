import json

from app.routing.extract import extract, inside_tiles, read_poly
from app.routing.osm import load_tiles, tile_path

# A square region covering tiles (0..3, 0..3); only the inner 2 x 2 tiles lie wholly inside it.
POLY = "region\n1\n   0.01 0.01\n   0.19 0.01\n   0.19 0.19\n   0.01 0.19\nEND\nEND\n"

OSM = """<?xml version='1.0' encoding='UTF-8'?>
<osm version="0.6">
  <node id="1" lat="0.06" lon="0.06" version="1"/>
  <node id="2" lat="0.07" lon="0.07" version="1"/>
  <node id="3" lat="0.11" lon="0.07" version="1"/>
  <node id="4" lat="0.06" lon="0.08" version="1"/>
  <node id="5" lat="0.07" lon="0.09" version="1"/>
  <way id="10" version="1"><nd ref="1"/><nd ref="2"/><nd ref="3"/><tag k="highway" v="path"/><tag k="surface" v="dirt"/></way>
  <way id="11" version="1"><nd ref="4"/><nd ref="5"/><tag k="highway" v="motorway"/></way>
  <way id="12" version="1"><nd ref="4"/><nd ref="5"/><tag k="waterway" v="stream"/></way>
</osm>
"""


def test_inside_tiles_skip_the_border(tmp_path):
    (tmp_path / "r.poly").write_text(POLY)
    assert inside_tiles(*read_poly(tmp_path / "r.poly")) == {(1, 1), (1, 2), (2, 1), (2, 2)}


def test_extract_writes_overpass_like_tiles(tmp_path):
    (tmp_path / "r.osm").write_text(OSM)
    (tmp_path / "r.poly").write_text(POLY)
    cache = tmp_path / "osm"
    cache.mkdir()
    tile_path((2, 2), cache).write_text(json.dumps({"nodes": {}, "ways": [], "kept": True}))

    assert extract(tmp_path / "r.osm", tmp_path / "r.poly", cache) == 3  # (2, 2) already cached
    assert json.loads(tile_path((2, 2), cache).read_text())["kept"]
    assert not tile_path((0, 0), cache).exists()  # border tile: left to Overpass

    osm = load_tiles([(1, 1)], cache)
    assert [(nodes, tags["highway"]) for nodes, tags in osm.ways] == [([1, 2, 3], "path")]  # motorway, stream left out
    assert osm.nodes[3] == (0.11, 0.07)  # nodes of the way beyond the tile come with it, like Overpass
    assert load_tiles([(2, 1)], cache).ways  # the way also crosses that tile
    assert load_tiles([(1, 2)], cache).ways == []  # inside the region, no path: written empty

    assert extract(tmp_path / "r.osm", tmp_path / "r.poly", cache, force=True) == 4
