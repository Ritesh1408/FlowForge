"""Alembic migrations against flowforge_test only (guards in conftest.run_alembic)."""

from collections.abc import Callable

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from flowforge.models import Base

pytestmark = pytest.mark.integration

AlembicRunner = Callable[[Connection, str, str], None]

APP_TABLES = {"workflows", "executions", "execution_steps", "execution_logs"}


def _app_tables(connection: Connection) -> set[str]:
    return set(inspect(connection).get_table_names()) & APP_TABLES


def _schema_diff(connection: Connection) -> list:
    return compare_metadata(MigrationContext.configure(connection), Base.metadata)


async def _migrate(engine: AsyncEngine, run_alembic: AlembicRunner, action: str, revision: str) -> set[str]:
    async with engine.begin() as connection:
        await connection.run_sync(run_alembic, action, revision)
        return await connection.run_sync(_app_tables)


async def test_upgrade_downgrade_upgrade(test_engine: AsyncEngine, alembic_runner: AlembicRunner) -> None:
    assert await _migrate(test_engine, alembic_runner, "upgrade", "head") == APP_TABLES
    assert await _migrate(test_engine, alembic_runner, "downgrade", "base") == set()
    assert await _migrate(test_engine, alembic_runner, "upgrade", "head") == APP_TABLES


async def test_migrated_schema_matches_models(test_engine: AsyncEngine, alembic_runner: AlembicRunner) -> None:
    await _migrate(test_engine, alembic_runner, "upgrade", "head")
    async with test_engine.connect() as connection:
        assert await connection.run_sync(_schema_diff) == []
