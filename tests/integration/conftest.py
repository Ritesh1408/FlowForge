"""Fixtures for integration tests against live local services.

Safety rules:
- PostgreSQL: only TEST_DATABASE_URL is used, never DATABASE_URL. Tests refuse to run
  unless the URL *and* the connected server-side database are exactly `flowforge_test`.
  Alembic is driven through an open test connection and re-checks current_database()
  before every command. Data tests run in a transaction that is rolled back.
- Redis: a dedicated DB index (15) is used, distinct from the development index;
  tests only touch keys they create and delete them afterwards. No FLUSHDB/FLUSHALL.
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from urllib.parse import urlsplit, urlunsplit

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from flowforge.core.config import PROJECT_ROOT, Settings
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


# --- Schema (Alembic) and per-test transactions -------------------------------------

ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"


def run_alembic(connection: Connection, action: str, revision: str) -> None:
    """Run an Alembic command on an open *test* connection (never via DATABASE_URL)."""
    name = connection.execute(text("SELECT current_database()")).scalar_one()
    if name != TEST_DATABASE_NAME:
        pytest.fail(f"Refusing to migrate database '{name}'; only '{TEST_DATABASE_NAME}' is allowed.")
    config = AlembicConfig(str(ALEMBIC_INI))
    config.attributes["connection"] = connection
    config.attributes["configure_logging"] = False
    getattr(command, action)(config, revision)


@pytest.fixture(scope="session")
def migrated_test_database(test_database_url: str) -> None:
    """Bring flowforge_test to the latest migration once per test session."""

    async def upgrade() -> None:
        engine = create_engine(test_database_url)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(run_alembic, "upgrade", "head")
        finally:
            await engine.dispose()

    asyncio.run(upgrade())


@pytest.fixture
async def db_session(test_engine: AsyncEngine, migrated_test_database: None) -> AsyncIterator[AsyncSession]:
    """Session inside an outer transaction that is always rolled back after the test.

    ``create_savepoint`` makes session.commit()/rollback() act on a SAVEPOINT, so code
    under test can commit or recover from errors without ending the outer transaction.
    """
    async with test_engine.connect() as connection:
        transaction = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            await session.close()
            await transaction.rollback()


@pytest.fixture
def alembic_runner() -> Callable[[Connection, str, str], None]:
    return run_alembic
