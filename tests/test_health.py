import asyncio
import logging

import httpx
import pytest

from flowforge.api.v1.health import get_health_service
from flowforge.core.config import Settings
from flowforge.main import create_app
from flowforge.services.health import HealthCheck, HealthService

SECRET_DETAIL = "db.internal:5432 password=hunter2"
TIMEOUT = 0.2


async def ok() -> None:
    return None


async def fail() -> None:
    raise ConnectionError(f"connection refused {SECRET_DETAIL}")


async def hang() -> None:
    await asyncio.sleep(30)


@pytest.fixture
def make_client(unit_settings: Settings):
    """Build an HTTP client whose health checks are replaced by fakes (no lifespan)."""

    def _make(postgresql: HealthCheck, redis: HealthCheck) -> httpx.AsyncClient:
        app = create_app(unit_settings)
        app.dependency_overrides[get_health_service] = lambda: HealthService(
            {"postgresql": postgresql, "redis": redis}, timeout_seconds=TIMEOUT
        )
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    return _make


async def get_health(client: httpx.AsyncClient) -> httpx.Response:
    async with client:
        return await client.get("/api/v1/health")


async def test_healthy_when_both_up(make_client) -> None:
    response = await get_health(make_client(ok, ok))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(
    ("postgresql", "redis"),
    [(fail, ok), (ok, fail), (fail, fail)],
    ids=["db-down", "redis-down", "both-down"],
)
async def test_unavailable_when_dependency_down(make_client, postgresql, redis) -> None:
    response = await get_health(make_client(postgresql, redis))

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}


@pytest.mark.parametrize(("postgresql", "redis"), [(hang, ok), (ok, hang)], ids=["db", "redis"])
async def test_timeout_returns_503(make_client, postgresql, redis) -> None:
    loop = asyncio.get_running_loop()
    started = loop.time()

    response = await get_health(make_client(postgresql, redis))

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert loop.time() - started < 5  # bounded by the timeout, not by the hang


async def test_response_contains_no_error_details(make_client, caplog) -> None:
    with caplog.at_level(logging.WARNING, logger="flowforge"):
        response = await get_health(make_client(fail, ok))

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    for leaked in ("hunter2", "db.internal", "5432", "ConnectionError", "postgresql"):
        assert leaked not in response.text
    # ...but the cause is kept in internal logs.
    assert "Health check 'postgresql' failed" in caplog.text


async def test_checks_run_concurrently() -> None:
    # The first check only completes if the second runs while it is waiting.
    released = asyncio.Event()

    async def waits_for_other() -> None:
        await released.wait()

    async def releases_other() -> None:
        released.set()

    service = HealthService({"a": waits_for_other, "b": releases_other}, timeout_seconds=1)

    assert await service.is_healthy() is True
