"""Settings load from the environment alone, without a .env file."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings

REQUIRED = {"DB_HOST": "localhost", "DB_USER": "u", "DB_PASS": "p", "DB_NAME": "d", "ORS_API_KEY": "k"}


def test_redis_url_is_optional(monkeypatch):
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("REDIS_URL", raising=False)
    assert Settings(_env_file=None).redis_url is None


def test_database_url_carries_port_and_sslmode(monkeypatch):
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)
    for name in ("DB_PORT", "DB_SSLMODE", "DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    local = Settings(_env_file=None).database_url
    assert (local.port, local.query) == (5432, {"sslmode": "prefer"})

    monkeypatch.setenv("DB_PORT", "6543")
    monkeypatch.setenv("DB_SSLMODE", "require")
    hosted = Settings(_env_file=None).database_url
    assert (hosted.port, hosted.query["sslmode"]) == (6543, "require")
    assert hosted.render_as_string(hide_password=True).endswith(":6543/d?sslmode=require")


NEON = "postgresql://u:p@ep-x-pooler.neon.tech/neondb?sslmode=require&channel_binding=require"
NEON_DIRECT = "postgresql://u:p@ep-x.neon.tech/neondb?sslmode=require&channel_binding=require"


def test_neon_database_urls(monkeypatch):
    for name in ("DB_HOST", "DB_USER", "DB_PASS", "DB_NAME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ORS_API_KEY", "k")
    monkeypatch.setenv("DATABASE_URL", NEON)
    monkeypatch.setenv("DATABASE_URL_UNPOOLED", NEON_DIRECT)
    s = Settings(_env_file=None)
    app, migrations = s.database_url, s.migration_database_url
    assert (app.drivername, app.host) == ("postgresql+psycopg2", "ep-x-pooler.neon.tech")
    assert app.query == {"sslmode": "require", "channel_binding": "require"}
    assert (migrations.drivername, migrations.host) == ("postgresql+psycopg2", "ep-x.neon.tech")


def test_migrations_fall_back_to_the_app_url(monkeypatch):
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)
    for name in ("DATABASE_URL", "DATABASE_URL_UNPOOLED"):
        monkeypatch.delenv(name, raising=False)
    s = Settings(_env_file=None)
    assert s.migration_database_url == s.database_url


def test_some_database_is_required(monkeypatch):
    for name in ("DB_HOST", "DB_USER", "DB_PASS", "DB_NAME", "DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ORS_API_KEY", "k")
    with pytest.raises(ValidationError, match="Set DATABASE_URL, or DB_HOST"):
        Settings(_env_file=None)


def neon_env(monkeypatch, pooled, direct):
    for name in ("DB_HOST", "DB_USER", "DB_PASS", "DB_NAME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ORS_API_KEY", "k")
    for name, value in (("DATABASE_URL", pooled), ("DATABASE_URL_UNPOOLED", direct)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


def test_app_and_migrations_on_different_databases_refuse_to_start(monkeypatch):
    # e.g. DATABASE_URL set for production while DATABASE_URL_UNPOOLED still comes from a dev branch's .env.local
    neon_env(monkeypatch, NEON, "postgresql://u:p@ep-other.neon.tech/neondb?sslmode=require")
    with pytest.raises(ValidationError, match="point at different databases"):
        Settings(_env_file=None)
    neon_env(monkeypatch, "postgresql://u:p@localhost:5432/waypoint", NEON_DIRECT)
    with pytest.raises(ValidationError, match="point at different databases"):
        Settings(_env_file=None)


def test_pooled_and_direct_urls_of_one_database_are_accepted(monkeypatch):
    neon_env(monkeypatch, NEON, NEON_DIRECT)
    assert Settings(_env_file=None).migration_database_url.host == "ep-x.neon.tech"


def test_without_database_url_migrations_follow_the_app(monkeypatch):
    # DATABASE_URL commented out to use a local Postgres; the leftover direct URL must not take migrations elsewhere
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)
    neon_env(monkeypatch, None, NEON_DIRECT)
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)
    s = Settings(_env_file=None)
    assert s.migration_database_url == s.database_url and s.database_url.host == "localhost"
