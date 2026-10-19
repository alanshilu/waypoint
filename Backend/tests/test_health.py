"""GET /health with the database engine stubbed."""

from contextlib import contextmanager
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.api.v1.endpoints import health as health_endpoint
from app.main import app


def engine_that(execute):
    @contextmanager
    def connect():
        yield SimpleNamespace(execute=execute)

    return SimpleNamespace(connect=connect)


def test_healthy_when_the_database_answers(monkeypatch):
    queries = []
    monkeypatch.setattr(health_endpoint.db, "engine", engine_that(lambda q: queries.append(str(q))))
    r = TestClient(app).get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "database": "ok"}
    assert queries == ["SELECT 1"]


def test_503_without_details_when_the_database_fails(monkeypatch):
    def fail(q):
        raise OperationalError("SELECT 1", {}, Exception("password authentication failed for user waypoint"))

    monkeypatch.setattr(health_endpoint.db, "engine", engine_that(fail))
    r = TestClient(app).get("/health")
    assert r.status_code == 503
    assert r.json() == {"status": "error", "database": "unreachable"}
    assert "password" not in r.text
