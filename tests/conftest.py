import pytest

from flowforge.core.config import Settings

# Unreachable placeholder URLs: unit tests must never touch real services.
UNIT_DATABASE_URL = "postgresql+asyncpg://unit:unit-secret@127.0.0.1:1/unit_db"
UNIT_REDIS_URL = "redis://:unit-secret@127.0.0.1:1/0"


@pytest.fixture
def unit_settings() -> Settings:
    """Settings that ignore `.env` and the process environment."""
    return Settings(
        _env_file=None,
        database_url=UNIT_DATABASE_URL,
        redis_url=UNIT_REDIS_URL,
        app_env="test",
    )
