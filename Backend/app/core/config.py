from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    db_host: str = Field(validation_alias="DB_HOST")
    db_user: str = Field(validation_alias="DB_USER")
    db_pass: str = Field(validation_alias="DB_PASS")
    db_name: str = Field(validation_alias="DB_NAME")
    redis_url: str = Field(validation_alias="REDIS_URL")
    ors_api_key: str = Field(validation_alias="ORS_API_KEY")
    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")

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
