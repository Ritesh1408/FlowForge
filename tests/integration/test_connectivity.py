import uuid

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from flowforge.core.config import Settings
from flowforge.db import session as db
from flowforge.main import create_app
from flowforge.queue import redis_client

pytestmark = pytest.mark.integration


async def test_postgresql_query_on_test_database(test_engine: AsyncEngine) -> None:
    async with test_engine.connect() as connection:
        row = (await connection.execute(text("SELECT current_database(), 1 + 1"))).one()

    assert tuple(row) == ("flowforge_test", 2)
    await db.ping(test_engine)


async def test_redis_ping_and_own_key_roundtrip(test_redis: Redis) -> None:
    assert test_redis.connection_pool.connection_kwargs["db"] == 15
    await redis_client.ping(test_redis)

    key = f"flowforge:test:{uuid.uuid4()}"
    try:
        await test_redis.set(key, "value", ex=60)
        assert await test_redis.get(key) == b"value"
    finally:
        await test_redis.delete(key)
    assert await test_redis.exists(key) == 0


async def test_health_endpoint_against_live_services(live_app_settings: Settings) -> None:
    app = create_app(live_app_settings)

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
