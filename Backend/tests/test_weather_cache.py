"""The weather HTTP cache: SQLite at WEATHER_CACHE_PATH, or memory when that can't be written."""

import importlib
import io
import os
import stat
import sys

import pytest
from requests.adapters import BaseAdapter, HTTPAdapter
from urllib3 import HTTPResponse

from app.core.config import settings
from app.services import weather_service


class FakeOpenMeteo(BaseAdapter):
    """Answers every request without the network and counts how many reached it."""

    def __init__(self):
        super().__init__()
        self.calls = 0

    def send(self, request, **kwargs):
        self.calls += 1
        raw = HTTPResponse(body=io.BytesIO(b'{"ok": true}'), headers={"Content-Type": "application/json"},
                           status=200, preload_content=False, request_url=request.url)
        return HTTPAdapter().build_response(request, raw)

    def close(self):
        pass


def fetch_twice(session) -> FakeOpenMeteo:
    fake = FakeOpenMeteo()
    session.mount("https://", fake)
    url = "https://api.open-meteo.com/v1/forecast?latitude=34.05&longitude=-118.24"
    first, second = session.get(url), session.get(url)
    assert first.json() == second.json() == {"ok": True}
    assert second.from_cache
    return fake


def unwritable_path(tmp_path):
    """A cache path under a regular file, which no platform can create a directory in."""
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("")
    return str(blocker / "cache" / "weather")


def test_writable_path_caches_in_sqlite(tmp_path):
    session = weather_service.make_cache_session(str(tmp_path / "weather"))
    assert session.cache.__class__.__name__ == "SQLiteCache"
    assert fetch_twice(session).calls == 1
    assert (tmp_path / "weather.sqlite").exists()


def test_unwritable_path_falls_back_to_memory(tmp_path, caplog):
    session = weather_service.make_cache_session(unwritable_path(tmp_path))
    assert session.cache.__class__.__name__ == "BaseCache"  # requests-cache's in-memory backend
    assert fetch_twice(session).calls == 1
    assert "caching in memory instead" in caplog.text


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0,
                    reason="needs POSIX permissions and a non-root user, like the container")
def test_read_only_directory_falls_back_to_memory(tmp_path):
    read_only = tmp_path / "read-only"
    read_only.mkdir()
    read_only.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        session = weather_service.make_cache_session(str(read_only / "weather"))
        assert session.cache.__class__.__name__ == "BaseCache"
        assert fetch_twice(session).calls == 1
    finally:
        read_only.chmod(stat.S_IRWXU)


def test_service_starts_and_fetches_with_an_unwritable_cache(tmp_path, monkeypatch):
    """Importing the service must not crash, and the session its Open-Meteo client uses still works."""
    monkeypatch.setattr(settings, "weather_cache_path", unwritable_path(tmp_path))
    try:
        service = importlib.reload(weather_service)
        assert service.cache_session.cache.__class__.__name__ == "BaseCache"
        assert fetch_twice(service.retry_session).calls == 1
    finally:
        monkeypatch.undo()
        importlib.reload(weather_service)
