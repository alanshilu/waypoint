"""Settings load from the environment alone, without a .env file."""

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
    for name in ("DB_PORT", "DB_SSLMODE"):
        monkeypatch.delenv(name, raising=False)
    local = Settings(_env_file=None).database_url
    assert (local.port, local.query) == (5432, {"sslmode": "prefer"})

    monkeypatch.setenv("DB_PORT", "6543")
    monkeypatch.setenv("DB_SSLMODE", "require")
    hosted = Settings(_env_file=None).database_url
    assert (hosted.port, hosted.query["sslmode"]) == (6543, "require")
    assert hosted.render_as_string(hide_password=True).endswith(":6543/d?sslmode=require")
