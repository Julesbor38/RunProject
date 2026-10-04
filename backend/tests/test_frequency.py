import json
import math
import os

import pytest

from app import api, frequency
from app.frequency import Grid, frequency_collection, level, pass_counts, split_by_passes
from app.routing.graph import EARTH_M_PER_DEG_LAT

LAT0, LON0 = 45.76, 4.78
GRID = Grid(LAT0)


def path(length_m: float = 1000, north_m: float = 0.0, east_m: float = 0.0, step_m: float = 20.0):
    """A straight west-east track, shifted by the given offsets (meters)."""
    n = int(length_m / step_m)
    lat = LAT0 + north_m / EARTH_M_PER_DEG_LAT
    return [[LON0 + (east_m + i * step_m) / GRID.kx, lat] for i in range(n + 1)]


def activity(fid: int, *lines, sport="run") -> dict:
    return {
        "type": "Feature",
        "id": fid,
        "geometry": {"type": "MultiLineString", "coordinates": list(lines)},
        "properties": {"sport": sport},
    }


def passes_of(fc: dict, fid: int) -> set[int]:
    return {f["properties"]["passes"] for f in fc["features"] if f["properties"]["activity"] == fid}


def drawn_m(fc: dict) -> float:
    """Total length of the drawn lines."""
    return sum(
        math.hypot((b[0] - a[0]) * GRID.kx, (b[1] - a[1]) * EARTH_M_PER_DEG_LAT)
        for f in fc["features"]
        for a, b in zip(f["geometry"]["coordinates"], f["geometry"]["coordinates"][1:])
    )


def test_out_and_back_in_one_activity_is_one_pass():
    there = path()
    back = [list(p) for p in reversed(path(north_m=6))]  # the way back, a few meters aside
    counts = pass_counts([[there + back]], GRID)
    assert max(counts.values()) == 1
    fc = frequency_collection({"features": [activity(0, there + back)]})
    assert passes_of(fc, 0) == {1}
    assert drawn_m(fc) == pytest.approx(1000, abs=60)  # the way back is not drawn beside the way out


def test_two_activities_on_same_path_with_gps_offset_are_two_passes():
    fc = frequency_collection({"features": [activity(0, path()), activity(1, path(north_m=9))]})
    assert {f["properties"]["passes"] for f in fc["features"]} == {2}
    assert drawn_m(fc) == pytest.approx(1000, abs=60)  # one line, not two side by side


def test_many_offset_runs_on_one_path_draw_a_single_line():
    runs = [activity(i, path(north_m=(i % 5 - 2) * 4, east_m=i % 3)) for i in range(12)]
    fc = frequency_collection({"features": runs})
    assert {f["properties"]["passes"] for f in fc["features"]} == {12}
    assert drawn_m(fc) == pytest.approx(1000, abs=60)


def test_branch_leaving_a_shared_path_is_drawn_and_joined():
    shared = path(500)
    branch = shared + [[shared[-1][0], shared[-1][1] + i * 20 / EARTH_M_PER_DEG_LAT] for i in range(1, 26)]
    fc = frequency_collection({"features": [activity(0, path(1000)), activity(1, branch)]})
    assert drawn_m(fc) == pytest.approx(1000 + 500, abs=80)
    tip = [round(c, 6) for c in branch[-1]]
    assert any(f["geometry"]["coordinates"][-1] == tip for f in fc["features"])


def test_parallel_paths_far_apart_are_counted_apart():
    fc = frequency_collection({"features": [activity(0, path()), activity(1, path(north_m=100))]})
    assert passes_of(fc, 0) == passes_of(fc, 1) == {1}


def test_track_is_split_where_the_pass_count_changes():
    long, half = path(1000), path(500)
    counts = pass_counts([[long], [half], [half]], GRID)
    pieces = split_by_passes(long, counts, GRID)
    assert [p for p, _ in pieces] == [3, 1]
    (_, first), (_, second) = pieces
    assert first[-1] == second[0]  # contiguous: no gap where the level changes
    assert first[0] == [round(c, 6) for c in long[0]] and second[-1] == [round(c, 6) for c in long[-1]]
    split_east_m = (first[-1][0] - LON0) * GRID.kx
    assert split_east_m == pytest.approx(500, abs=3 * frequency.CELL_M)


def test_crossing_path_does_not_darken_the_track():
    """A run crossing another one at right angles shares a few cells only: no darker blip."""
    north_south = [[LON0 + 500 / GRID.kx, LAT0 + (i * 20 - 500) / EARTH_M_PER_DEG_LAT] for i in range(51)]
    counts = pass_counts([[path()], [north_south]], GRID)
    assert [p for p, _ in split_by_passes(path(), counts, GRID)] == [1]


def test_levels_bucket_counts():
    assert [level(n) for n in (1, 2, 4, 7, 12, 30, 400)] == [1, 2, 3, 5, 10, 20, 50]


def test_collection_flags_sports_and_draws_busiest_last():
    fc = frequency_collection({"features": [
        activity(0, path(), sport="trail_run"),
        activity(1, path(north_m=4)),
        activity(2, path(north_m=300), sport="hike"),
    ]})
    passes = [f["properties"]["passes"] for f in fc["features"]]
    assert passes == sorted(passes)
    assert fc["max_passes"] == 2
    shared = [f["properties"] for f in fc["features"] if f["properties"]["passes"] == 2]
    hike = [f["properties"] for f in fc["features"] if f["properties"]["activity"] == 2]
    assert shared and all(p["run"] and p["trail_run"] and not p["hike"] for p in shared)
    assert hike and all(p["hike"] and not p["run"] and not p["trail_run"] for p in hike)


def test_frequency_cache_is_reused_until_activities_change(tmp_path, monkeypatch):
    (tmp_path / "cache").mkdir()
    fc = {"type": "FeatureCollection", "features": [activity(0, path())]}
    activities = tmp_path / "cache" / "activities.geojson"
    activities.write_text(json.dumps(fc))
    first = api.load_frequency(tmp_path, fc)
    assert (tmp_path / "cache" / "frequency.geojson").exists()

    def boom(*_):
        raise AssertionError("recomputed although activities did not change")

    monkeypatch.setattr(frequency, "frequency_collection", boom)
    assert api.load_frequency(tmp_path, fc) == first

    later = (tmp_path / "cache" / "frequency.geojson").stat().st_mtime + 10
    os.utime(activities, (later, later))
    with pytest.raises(AssertionError, match="recomputed"):
        api.load_frequency(tmp_path, fc)


def test_frequency_cache_is_recomputed_when_settings_change(tmp_path, monkeypatch):
    (tmp_path / "cache").mkdir()
    fc = {"type": "FeatureCollection", "features": [activity(0, path())]}
    (tmp_path / "cache" / "activities.geojson").write_text(json.dumps(fc))
    api.load_frequency(tmp_path, fc)
    monkeypatch.setattr(frequency, "SIGNATURE", "other settings")
    assert api.load_frequency(tmp_path, fc)["signature"] == "other settings"


# --- drawing on OSM ways ---

def way(length_m=1000, north_m=0.0, east_m=0.0, step_m=50.0):
    """An OSM way as a line (sparse vertices, like OSM)."""
    return path(length_m, north_m, east_m, step_m)


def north_of(feature) -> list[float]:
    """Offsets (meters, north of LAT0) of a drawn line's vertices."""
    return [(lat - LAT0) * EARTH_M_PER_DEG_LAT for _, lat in feature["geometry"]["coordinates"]]


def test_runs_with_gps_offset_are_drawn_on_the_street_itself():
    street = way()
    runs = [activity(i, path(north_m=(-6, 3, 8)[i])) for i in range(3)]
    fc = frequency_collection({"features": runs}, [(street, ("Rue A", "residential"))])
    assert fc["features"]
    assert all(abs(n) < 0.5 for f in fc["features"] for n in north_of(f))  # on the way, not on a GPS line
    assert {f["properties"]["passes"] for f in fc["features"]} == {3}
    assert drawn_m(fc) == pytest.approx(1000, abs=30)  # the whole street, without gaps


def test_sidewalk_like_path_beside_the_street_is_not_drawn_twice():
    road, footway = way(), way(north_m=8)
    runs = [activity(i, path(north_m=1)) for i in range(2)]
    fc = frequency_collection({"features": runs}, [(road, ("Rue A", "residential")), (footway, None)])
    assert drawn_m(fc) == pytest.approx(1000, abs=60)


def test_crossed_street_is_not_drawn_but_the_street_run_along_is_whole():
    along = way()
    across = [[LON0 + 500 / GRID.kx, LAT0 + (i * 50 - 500) / EARTH_M_PER_DEG_LAT] for i in range(21)]
    fc = frequency_collection({"features": [activity(0, path(north_m=4))]}, [(along, ("Rue A", "residential")), (across, ("Rue B", "residential"))])
    assert drawn_m(fc) == pytest.approx(1000, abs=60)
    assert all(abs(n) < 0.5 for f in fc["features"] for n in north_of(f))


def test_both_carriageways_of_an_avenue_are_drawn():
    north, south = way(north_m=10), way(north_m=-10)
    runs = [activity(0, path(north_m=9)), activity(1, path(north_m=-9))]
    key = ("Avenue C", "tertiary")
    fc = frequency_collection({"features": runs}, [(north, key), (south, key)])
    assert drawn_m(fc) == pytest.approx(2000, abs=100)


def test_tracks_off_any_osm_way_are_drawn_themselves():
    street = way(500)  # mapped for the first half only
    fc = frequency_collection({"features": [activity(0, path(1000, north_m=3))]}, [(street, ("Rue A", "residential"))])
    assert drawn_m(fc) == pytest.approx(1000, abs=80)
    assert max(c[0] for f in fc["features"] for c in f["geometry"]["coordinates"]) == pytest.approx(path(1000)[-1][0], abs=1e-5)


def test_gap_where_the_gps_left_the_street_is_filled():
    """The runs drift 40 m off the street for 80 m: the street is still drawn whole."""
    def drifting(i):
        return [[LON0 + x / GRID.kx, LAT0 + ((40 if 460 <= x <= 540 else 0) + i) / EARTH_M_PER_DEG_LAT] for x in range(0, 1001, 20)]
    runs = [activity(i, drifting(i)) for i in range(3)]
    fc = frequency_collection({"features": runs}, [(way(), ("Rue A", "residential"))])
    on_street = [f for f in fc["features"] if all(abs(n) < 0.5 for n in north_of(f))]
    assert sum(math.hypot((b[0] - a[0]) * GRID.kx, (b[1] - a[1]) * EARTH_M_PER_DEG_LAT)
               for f in on_street for a, b in zip(f["geometry"]["coordinates"], f["geometry"]["coordinates"][1:])) == pytest.approx(1000, abs=30)


def test_shown_level_does_not_flicker_along_a_street():
    """10 runs along the whole street, an 11th... and a few on alternate 100 m stretches."""
    runs = [activity(i, path()) for i in range(9)]
    runs += [activity(9 + k, path(100, east_m=200 * k)) for k in range(5)]  # 10 passes on every other stretch
    fc = frequency_collection({"features": runs}, [(way(), ("Rue A", "residential"))])
    assert len({level(f["properties"]["passes"]) for f in fc["features"]}) == 1
    assert len(fc["features"]) == 1  # one continuous line


def test_side_street_start_is_not_drawn():
    main = way()
    side = [[LON0 + 500 / GRID.kx, LAT0 + i * 30 / EARTH_M_PER_DEG_LAT] for i in range(11)]
    fc = frequency_collection({"features": [activity(0, path(north_m=3))]}, [(main, ("Rue A", "residential")), (side, ("Rue B", "residential"))])
    assert all(abs(n) < 0.5 for f in fc["features"] for n in north_of(f))
