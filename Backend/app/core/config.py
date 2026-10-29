import logging
from pathlib import Path

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

log = logging.getLogger(__name__)


class Settings(BaseSettings):
    # Neon: `neon env pull` writes the pooled URL (app traffic) and the direct one (migrations).
    # When DATABASE_URL is set it wins and the DB_* settings below are ignored.
    database_url_env: str | None = Field(default=None, validation_alias="DATABASE_URL")
    database_url_unpooled_env: str | None = Field(default=None, validation_alias="DATABASE_URL_UNPOOLED")
    # Any other Postgres, e.g. a local one
    db_host: str | None = Field(default=None, validation_alias="DB_HOST")
    db_user: str | None = Field(default=None, validation_alias="DB_USER")
    db_pass: str | None = Field(default=None, validation_alias="DB_PASS")
    db_name: str | None = Field(default=None, validation_alias="DB_NAME")
    db_port: int = Field(default=5432, validation_alias="DB_PORT")
    # libpq sslmode: "prefer" works locally; hosted Postgres such as Neon needs "require"
    db_sslmode: str = Field(default="prefer", validation_alias="DB_SSLMODE")
    # Optional and unused for now: agent sessions are in memory (app/agent/sessions.py)
    redis_url: str | None = Field(default=None, validation_alias="REDIS_URL")
    ors_api_key: str = Field(validation_alias="ORS_API_KEY")
    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")

    # Agent. Model ids are configuration, never hardcoded in the agent code.
    agent_model: str = Field(default="claude-sonnet-5-5", validation_alias="AGENT_MODEL")
    agent_effort: str = Field(default="medium", validation_alias="AGENT_EFFORT")
    eval_judge_model: str = Field(default="claude-haiku-5-5", validation_alias="EVAL_JUDGE_MODEL")
    # The agent's tools call this API over HTTP
    api_base_url: str = Field(default="http://localhost:8000", validation_alias="API_BASE_URL")
    # Geoapify Places (OpenStreetMap data, hosted): the first source for places to stay and eat when set.
    # Free plan: 3,000 credits a day (1 per 20 places), 5 requests a second; unset, Overpass is the first source.
    geoapify_api_key: str | None = Field(default=None, validation_alias="GEOAPIFY_API_KEY")
    # OpenStreetMap Overpass servers for places to stay and eat, tried in order (comma-separated).
    # Free public services with a fair-use policy; results are cached for a day.
    overpass_urls: str = Field(
        default="https://overpass-api.de/api/interpreter,https://overpass.kumi.systems/api/interpreter",
        validation_alias="OVERPASS_URLS",
    )
    # Open-Meteo responses are cached for an hour in SQLite here (".sqlite" is appended). Kept out of the
    # working directory, which a non-root container can't write; if this can't be created either, the
    # cache falls back to memory.
    weather_cache_path: str = Field(default="/tmp/waypoint_weather_cache", validation_alias="WEATHER_CACHE_PATH")
    # Seconds to wait for one OpenRouteService directions request; long drives can take a minute when ORS is busy
    ors_route_timeout_s: float = Field(default=90.0, validation_alias="ORS_ROUTE_TIMEOUT_S")
    # Seconds for all attempts at one route together: a timeout, 429 or 5xx is retried (up to 3 attempts, with
    # backoff) while another attempt fits. Unset: three attempts' worth. Either way at most half of
    # AGENT_TIMEOUT_S (see ors_route_retry_budget_s), and an agent turn's own deadline cuts it shorter still.
    ors_route_retry_budget_env: float | None = Field(default=None, gt=0, validation_alias="ORS_ROUTE_RETRY_BUDGET_S")

    # Browser origins allowed by CORS, comma-separated: the Vite dev server plus
    # the deployed frontend, e.g. "http://localhost:5173,https://waypoint.example.com"
    cors_origins: str = Field(default="http://localhost:5173", validation_alias="CORS_ORIGINS")

    # POST /agent/message: a safety net for a turn that never ends, not a budget. The place search waits
    # for OpenStreetMap as long as it takes (each Overpass query ends on the server within 180 s, a wider
    # food search can follow), and the app shows the user it's still working, so this is generous.
    agent_timeout_s: float = Field(default=900.0, validation_alias="AGENT_TIMEOUT_S")
    agent_rate_limit_per_minute: int = Field(default=10, validation_alias="AGENT_RATE_LIMIT_PER_MINUTE")
    agent_session_ttl_s: int = Field(default=1800, validation_alias="AGENT_SESSION_TTL_S")
    # Cost limits for a public demo; 0 turns a limit off. The daily cap resets at midnight UTC.
    agent_max_sessions: int = Field(default=200, validation_alias="AGENT_MAX_SESSIONS")
    agent_sessions_per_ip_per_hour: int = Field(default=5, validation_alias="AGENT_SESSIONS_PER_IP_PER_HOUR")
    agent_daily_turn_cap: int = Field(default=200, validation_alias="AGENT_DAILY_TURN_CAP")
    # GET /shared/{public_id} (a trip opened from its share link): requests per client address per minute
    shared_rate_limit_per_minute: int = Field(default=30, validation_alias="SHARED_RATE_LIMIT_PER_MINUTE")
    # User turns kept per session; older turns are dropped from the front
    agent_history_max_turns: int = Field(default=12, validation_alias="AGENT_HISTORY_MAX_TURNS")

    # Public deployment: GET /trips/trips is off, and the trip and route write endpoints only answer
    # callers that send INTERNAL_API_TOKEN in the X-Waypoint-Internal header (the agent's tools do)
    public_demo: bool = Field(default=False, validation_alias="PUBLIC_DEMO")
    # INTERNAL_API_SECRET is the earlier name, still accepted
    internal_api_token: str | None = Field(
        default=None, validation_alias=AliasChoices("INTERNAL_API_TOKEN", "INTERNAL_API_SECRET")
    )

    @model_validator(mode="after")
    def _public_demo_needs_a_secret(self):
        if self.public_demo and not self.internal_api_token:
            raise ValueError("PUBLIC_DEMO=true needs INTERNAL_API_TOKEN, or the agent cannot create trips")
        return self

    @property
    def overpass_url_list(self) -> list[str]:
        return [u.strip() for u in self.overpass_urls.split(",") if u.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def ors_route_retry_budget_s(self) -> float:
        """
        Seconds for all attempts at one route: ORS_ROUTE_RETRY_BUDGET_S, or three attempts' worth when it's unset,
        never more than half of AGENT_TIMEOUT_S, so the model calls and the other tools keep the other half of the
        turn. Never a reason to refuse to start: a value too large for the turn is lowered (and logged once).
        """
        wanted = self.ors_route_retry_budget_env or self.ors_route_timeout_s * 3 + 30
        return min(wanted, self.agent_timeout_s / 2)

    @model_validator(mode="after")
    def _say_when_route_retries_are_cut(self):
        if self.ors_route_retry_budget_env and self.ors_route_retry_budget_env > self.agent_timeout_s / 2:
            log.warning("ORS_ROUTE_RETRY_BUDGET_S=%g is more than half of AGENT_TIMEOUT_S=%g; using %g s",
                        self.ors_route_retry_budget_env, self.agent_timeout_s, self.ors_route_retry_budget_s)
        return self

    @model_validator(mode="after")
    def _needs_a_database(self):
        missing = [n for n, v in [("DB_HOST", self.db_host), ("DB_USER", self.db_user),
                                  ("DB_PASS", self.db_pass), ("DB_NAME", self.db_name)] if not v]
        if not self.database_url_env and missing:
            raise ValueError(f"Set DATABASE_URL, or {', '.join(missing)}")
        return self

    @model_validator(mode="after")
    def _migrations_and_app_share_a_database(self):
        # The two URLs can come from different places (an environment variable and .env.local, say).
        # Pointing at different databases would migrate one and serve the other, so refuse to start.
        if self.database_url_env and self.database_url_unpooled_env:
            app_db = _database_identity(self.database_url_env)
            migration_db = _database_identity(self.database_url_unpooled_env)
            if app_db != migration_db:
                raise ValueError(
                    f"DATABASE_URL ({app_db[0]}/{app_db[1]}) and DATABASE_URL_UNPOOLED ({migration_db[0]}/"
                    f"{migration_db[1]}) point at different databases; set both from the same branch, or neither"
                )
        return self

    # Backend/.env, plus the .env.local that `neon env pull` writes in the repo root.
    # Real environment variables (Render, docker-compose) override both.
    model_config = SettingsConfigDict(
        env_file=(Path(__file__).resolve().parents[3] / ".env.local", Path(__file__).resolve().parents[2] / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        # A settings error names the field and the rule, never the values: they hold the database URL and API
        # keys, and the error goes to the host's logs
        hide_input_in_errors=True,
    )

    @staticmethod
    def _psycopg2(url: str) -> URL:
        # Neon's URLs say postgresql://; keep their sslmode and channel_binding parameters
        return make_url(url).set(drivername="postgresql+psycopg2")

    @property
    def database_url(self) -> URL:
        """For the app: Neon's pooled connection when DATABASE_URL is set."""
        if self.database_url_env:
            return self._psycopg2(self.database_url_env)
        return URL.create(
            "postgresql+psycopg2",
            username=self.db_user,
            password=self.db_pass,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
            query={"sslmode": self.db_sslmode},
        )

    @property
    def migration_database_url(self) -> URL:
        """
        For Alembic: a direct connection, since Neon's pooler (transaction mode) drops session state. Only
        alongside DATABASE_URL: without it the app is on DB_*, and migrations must go there too.
        """
        if self.database_url_env and self.database_url_unpooled_env:
            return self._psycopg2(self.database_url_unpooled_env)
        return self.database_url


def _database_identity(url: str) -> tuple[str, str]:
    """(host, database), with Neon's "-pooler" suffix taken off the endpoint so pooled and direct match."""
    parsed = make_url(url)
    host = (parsed.host or "").replace("-pooler.", ".", 1)
    return host, parsed.database or ""


# Import this single instance anywhere you need config:
#   from app.core.config import settings
settings = Settings()
