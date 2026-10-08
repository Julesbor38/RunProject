import pytest

from app import api


@pytest.fixture(autouse=True)
def no_osm_prefetch(monkeypatch):
    """The API must never reach Overpass during tests."""
    monkeypatch.setattr(api, "PREFETCH_OSM", False)
    monkeypatch.setattr(api, "EXPLORE_AUTO", False)
    monkeypatch.setattr(api, "ROUTE_CREDITS", False)  # free routes, except in the credits tests


@pytest.fixture(autouse=True)
def logged_in(request, monkeypatch):
    """API tests run as a logged-in user, except those marked `auth` which test the login itself."""
    if "auth" not in request.keywords:
        monkeypatch.setattr(api, "session_user", lambda data_dir, token: "tester")


def pytest_configure(config):
    config.addinivalue_line("markers", "auth: test the real login (no automatic session)")
