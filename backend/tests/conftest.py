import pytest

from app import api


@pytest.fixture(autouse=True)
def no_osm_prefetch(monkeypatch):
    """The API must never reach Overpass during tests."""
    monkeypatch.setattr(api, "PREFETCH_OSM", False)
