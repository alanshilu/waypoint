"""GET /health (liveness, no database) and GET /ready (SELECT 1), with the database engine stubbed."""

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


def failing(q):
    raise OperationalError("SELECT 1", {}, Exception("password authentication failed for user waypoint"))


def test_health_never_touches_the_database(monkeypatch):
    def no_database():
        raise AssertionError("/health must not connect to the database")

    monkeypatch.setattr(health_endpoint.db, "engine", SimpleNamespace(connect=no_database))
    r = TestClient(app).get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_ready_when_the_database_answers(monkeypatch):
    queries = []
    monkeypatch.setattr(health_endpoint.db, "engine", engine_that(lambda q: queries.append(str(q))))
    r = TestClient(app).get("/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "database": "ok"}
    assert queries == ["SELECT 1"]


def test_ready_is_503_without_details_when_the_database_fails(monkeypatch):
    monkeypatch.setattr(health_endpoint.db, "engine", engine_that(failing))
    r = TestClient(app).get("/ready")
    assert r.status_code == 503
    assert r.json() == {"status": "error", "database": "unreachable"}
    assert "password" not in r.text


def test_health_stays_up_while_the_database_is_down(monkeypatch):
    monkeypatch.setattr(health_endpoint.db, "engine", engine_that(failing))
    assert TestClient(app).get("/health").status_code == 200
