import gzip
from pathlib import Path

import pytest

from app.ingest import iter_strava_archive, parse_file

GPX = """<?xml version="1.0"?>
<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">
 <trk><name>Test</name><type>running</type><trkseg>
  <trkpt lat="45.7671" lon="4.6514"><ele>480</ele><time>2026-10-03T13:44:39Z</time></trkpt>
  <trkpt lat="45.7680" lon="4.6514"><ele>490</ele><time>2026-10-03T13:45:39Z</time></trkpt>
  <trkpt lat="45.7689" lon="4.6514"><ele>500</ele><time>2026-10-03T13:46:39Z</time></trkpt>
 </trkseg></trk></gpx>"""

TCX = """<?xml version="1.0"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
 <Activities><Activity Sport="Running"><Lap><Track>
  <Trackpoint><Time>2026-10-03T13:44:39Z</Time><Position><LatitudeDegrees>45.7671</LatitudeDegrees>
   <LongitudeDegrees>4.6514</LongitudeDegrees></Position><AltitudeMeters>480</AltitudeMeters>
   <HeartRateBpm><Value>150</Value></HeartRateBpm></Trackpoint>
  <Trackpoint><Time>2026-10-03T13:45:39Z</Time><Position><LatitudeDegrees>45.7680</LatitudeDegrees>
   <LongitudeDegrees>4.6514</LongitudeDegrees></Position><AltitudeMeters>490</AltitudeMeters></Trackpoint>
 </Track></Lap></Activity></Activities></TrainingCenterDatabase>"""


def test_gpx(tmp_path: Path):
    f = tmp_path / "a.gpx"
    f.write_text(GPX)
    a = parse_file(f)
    assert len(a.points) == 3 and a.sport == "run"
    assert a.distance_m == pytest.approx(200, rel=0.02)
    assert a.ascent_m == pytest.approx(20)


def test_tcx_gz(tmp_path: Path):
    f = tmp_path / "a.tcx.gz"
    f.write_bytes(gzip.compress(TCX.encode()))
    a = parse_file(f)
    assert len(a.points) == 2 and a.points[0].hr == 150 and a.sport == "run"


def test_strava_archive_filters_runs(tmp_path: Path):
    (tmp_path / "activities").mkdir()
    (tmp_path / "activities" / "1.gpx").write_text(GPX)
    (tmp_path / "activities" / "2.gpx").write_text(GPX)
    (tmp_path / "activities.csv").write_text(
        "Activity ID,Activity Date,Activity Name,Activity Type,Filename\n"
        "1,x,Sortie trail,Trail Run,activities/1.gpx\n"
        "2,x,Vélo,Ride,activities/2.gpx\n"
        "3,x,Tapis,Run,\n"
        "4,x,Rando,Randonnée,activities/2.gpx\n"
    )
    acts = list(iter_strava_archive(tmp_path))
    assert len(acts) == 2
    assert acts[0].sport == "trail_run" and acts[0].source == "strava:1"
    assert acts[1].sport == "hike" and acts[1].source == "strava:4"


SAMPLE_FIT = Path(__file__).parents[2] / "data" / "users" / "jules" / "raw" / "PollionnayTrail20261003154439.fit"


@pytest.mark.skipif(not SAMPLE_FIT.exists(), reason="sample .fit not present")
def test_real_coros_fit():
    a = parse_file(SAMPLE_FIT)
    assert a.sport == "trail_run"
    assert a.distance_m == pytest.approx(16_400, rel=0.03)
