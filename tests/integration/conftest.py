"""Fixtures for integration tests against live local services.

Safety rules:
- PostgreSQL: only TEST_DATABASE_URL is used, never DATABASE_URL. Tests refuse to run
  unless the URL *and* the connected server-side database are exactly `flowforge_test`.
- Redis: a dedicated DB index (15) is used, distinct from the development index;
  tests only touch keys they create and delete them afterwards. No FLUSHDB/FLUSHALL.
"""

from collections.abc import AsyncIterator
from urllib.parse import urlsplit, urlunsplit

import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine

from flowforge.core.config import Settings
from flowforge.db.session import create_engine
from flowforge.queue.redis_client import create_redis_client

TEST_DATABASE_NAME = "flowforge_test"
TEST_REDIS_DB = 15


def _redis_db_index(url: str) -> int:
    path = urlsplit(url).path.strip("/")
    return int(path) if path else 0


def _with_redis_db(url: str, db: int) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=f"/{db}"))


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings()


@pytest.fixture(scope="session")
def test_database_url(settings: Settings) -> str:
    if settings.test_database_url is None:
        pytest.fail(
            "TEST_DATABASE_URL is not set; integration tests never fall back to DATABASE_URL. "
            'Set it in .env or run unit tests only with: pytest -m "not integration"'
        )
    url = settings.test_database_url.get_secret_value()
    if make_url(url).database != TEST_DATABASE_NAME:
        pytest.fail(f"TEST_DATABASE_URL must point at database '{TEST_DATABASE_NAME}'; refusing to run.")
    return url


@pytest.fixture(scope="session")
def test_redis_url(settings: Settings) -> str:
    dev_url = settings.redis_url.get_secret_value()
    if _redis_db_index(dev_url) == TEST_REDIS_DB:
        pytest.fail(f"REDIS_URL uses DB {TEST_REDIS_DB}, which is reserved for tests; refusing to run.")
    return _with_redis_db(dev_url, TEST_REDIS_DB)


@pytest.fixture
async def test_engine(test_database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(test_database_url)
    try:
        async with engine.connect() as connection:
            name = (await connection.execute(text("SELECT current_database()"))).scalar_one()
        if name != TEST_DATABASE_NAME:
            pytest.fail(f"Connected to database '{name}', expected '{TEST_DATABASE_NAME}'; refusing to run.")
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def test_redis(test_redis_url: str) -> AsyncIterator[Redis]:
    client = create_redis_client(test_redis_url)
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
def live_app_settings(settings: Settings, test_engine: AsyncEngine, test_redis_url: str) -> Settings:
    """App settings wired to the guarded test database and test Redis DB."""
    return settings.model_copy(
        update={
            "database_url": settings.test_database_url,
            "redis_url": type(settings.redis_url)(test_redis_url),
            "app_env": "test",
        }
    )
