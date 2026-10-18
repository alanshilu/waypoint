"""Settings load from the environment alone, without a .env file."""

from app.core.config import Settings

REQUIRED = {"DB_HOST": "localhost", "DB_USER": "u", "DB_PASS": "p", "DB_NAME": "d", "ORS_API_KEY": "k"}


def test_redis_url_is_optional(monkeypatch):
    for name, value in REQUIRED.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("REDIS_URL", raising=False)
    assert Settings(_env_file=None).redis_url is None
