"""Centralized application settings, loaded from environment variables and `.env`."""

import logging
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration.

    Connection URLs may embed credentials, so they are stored as ``SecretStr`` and are
    masked in ``repr()``/``str()``. Call ``.get_secret_value()`` only where the raw URL
    is needed to open a connection.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: SecretStr
    test_database_url: SecretStr | None = None
    redis_url: SecretStr
    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    health_check_timeout_seconds: float = Field(default=2.0, gt=0)

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        level = value.strip().upper()
        if level not in logging.getLevelNamesMapping():
            raise ValueError(f"Unknown log level: {value!r}")
        return level


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""
    return Settings()
