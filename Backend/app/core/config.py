from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    db_host: str = Field(validation_alias="DB_HOST")
    db_user: str = Field(validation_alias="DB_USER")
    db_pass: str = Field(validation_alias="DB_PASS")
    db_name: str = Field(validation_alias="DB_NAME")
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
    # Seconds to wait for one OpenRouteService directions request; long drives can take a minute when ORS is busy
    ors_route_timeout_s: float = Field(default=90.0, validation_alias="ORS_ROUTE_TIMEOUT_S")

    # Browser origins allowed by CORS, comma-separated: the Vite dev server plus
    # the deployed frontend, e.g. "http://localhost:5173,https://waypoint.example.com"
    cors_origins: str = Field(default="http://localhost:5173", validation_alias="CORS_ORIGINS")

    # POST /agent/message
    # Covers a slow route generation (ORS_ROUTE_TIMEOUT_S) plus the other tool and model calls of a turn
    agent_timeout_s: float = Field(default=180.0, validation_alias="AGENT_TIMEOUT_S")
    agent_rate_limit_per_minute: int = Field(default=10, validation_alias="AGENT_RATE_LIMIT_PER_MINUTE")
    agent_session_ttl_s: int = Field(default=1800, validation_alias="AGENT_SESSION_TTL_S")
    # Cost limits for a public demo; 0 turns a limit off. The daily cap resets at midnight UTC.
    agent_max_sessions: int = Field(default=200, validation_alias="AGENT_MAX_SESSIONS")
    agent_sessions_per_ip_per_hour: int = Field(default=5, validation_alias="AGENT_SESSIONS_PER_IP_PER_HOUR")
    agent_daily_turn_cap: int = Field(default=200, validation_alias="AGENT_DAILY_TURN_CAP")
    # User turns kept per session; older turns are dropped from the front
    agent_history_max_turns: int = Field(default=12, validation_alias="AGENT_HISTORY_MAX_TURNS")

    # Public deployment: GET /trips/trips is off, and the trip and route write endpoints only answer
    # callers that send INTERNAL_API_SECRET in the X-Waypoint-Internal header (the agent's tools do)
    public_demo: bool = Field(default=False, validation_alias="PUBLIC_DEMO")
    internal_api_secret: str | None = Field(default=None, validation_alias="INTERNAL_API_SECRET")

    @model_validator(mode="after")
    def _public_demo_needs_a_secret(self):
        if self.public_demo and not self.internal_api_secret:
            raise ValueError("PUBLIC_DEMO=true needs INTERNAL_API_SECRET, or the agent cannot create trips")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
    )

    @property
    def database_url(self) -> URL:
        return URL.create(
            "postgresql+psycopg2",
            username=self.db_user,
            password=self.db_pass,
            host=self.db_host,
            database=self.db_name,
        )


# Import this single instance anywhere you need config:
#   from app.core.config import settings
settings = Settings()
