"""Execution creation and queueing against the real flowforge_test database and Redis DB 15.

The app runs with its real lifespan (so the queue uses the app's Redis client and
settings) but its session dependency is overridden with the rolled-back ``db_session``.
Each test uses its own queue key and deletes it afterwards.
"""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import func, select, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from flowforge.api.v1.workflows import get_execution_queue
from flowforge.core.config import Settings
from flowforge.db.session import get_session
from flowforge.main import create_app
from flowforge.models import Execution, ExecutionLog, ExecutionStep, Workflow
from flowforge.queue.execution_queue import ExecutionQueue, decode_message
from flowforge.queue.redis_client import create_redis_client

pytestmark = pytest.mark.integration

DEFINITION = {
    "steps": [
        {"name": "fetch", "type": "http", "config": {"url": "https://example.com/orders"}},
        {"name": "wait", "type": "delay", "config": {"seconds": 1}},
        {"name": "note", "type": "demo", "config": {"message": "done"}},
    ]
}
UNREACHABLE_REDIS_URL = "redis://127.0.0.1:1/15"


@pytest.fixture
async def queue_key(test_redis: Redis) -> AsyncIterator[str]:
    key = f"flowforge:test:queue:{uuid.uuid4()}"
    try:
        yield key
    finally:
        await test_redis.delete(key)
    assert await test_redis.exists(key) == 0


@pytest.fixture
async def app(live_app_settings: Settings, db_session: AsyncSession, queue_key: str) -> AsyncIterator[FastAPI]:
    app = create_app(live_app_settings.model_copy(update={"execution_queue_key": queue_key}))

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = session_override
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.fixture
async def unreachable_queue(app: FastAPI, queue_key: str) -> AsyncIterator[None]:
    """Point the endpoint at a Redis that refuses connections (a real failure, not a mock)."""
    redis = create_redis_client(UNREACHABLE_REDIS_URL)
    app.dependency_overrides[get_execution_queue] = lambda: ExecutionQueue(redis, queue_key, timeout_seconds=2)
    try:
        yield
    finally:
        await redis.aclose()


async def _workflow_id(client: httpx.AsyncClient, name: str = "orders") -> uuid.UUID:
    response = await client.post("/api/v1/workflows", json={"name": name, "definition": DEFINITION})
    assert response.status_code == 201
    return uuid.UUID(response.json()["id"])


async def _execute(client: httpx.AsyncClient, workflow_id: uuid.UUID, body: Any = None) -> httpx.Response:
    url = f"/api/v1/workflows/{workflow_id}/execute"
    return await client.post(url) if body is None else await client.post(url, json=body)


async def _queued_ids(redis: Redis, key: str) -> list[uuid.UUID]:
    """Messages in FIFO (consumption) order: LPUSH adds on the left, workers pop on the right."""
    return [decode_message(raw) for raw in reversed(await redis.lrange(key, 0, -1))]


async def _executions(session: AsyncSession, workflow_id: uuid.UUID) -> list[Execution]:
    session.expunge_all()
    statement = select(Execution).where(Execution.workflow_id == workflow_id).order_by(Execution.created_at)
    return list((await session.scalars(statement)).all())


async def _steps(session: AsyncSession, execution_id: uuid.UUID) -> list[ExecutionStep]:
    statement = select(ExecutionStep).where(ExecutionStep.execution_id == execution_id).order_by(ExecutionStep.position)
    return list((await session.scalars(statement)).all())


async def _log_events(session: AsyncSession, execution_id: uuid.UUID) -> list[tuple[str, str]]:
    statement = (
        select(ExecutionLog.level, ExecutionLog.event)
        .where(ExecutionLog.execution_id == execution_id)
        .order_by(ExecutionLog.id)
    )
    return [tuple(row) for row in (await session.execute(statement)).all()]


async def _total(session: AsyncSession, model: type) -> int:
    return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def test_execute_creates_queued_execution_and_enqueues_it(
    client: httpx.AsyncClient, db_session: AsyncSession, test_redis: Redis, queue_key: str
) -> None:
    workflow_id = await _workflow_id(client)

    response = await _execute(client, workflow_id, {"input": {"order_id": 42, "items": [{"sku": "A1"}]}})

    assert response.status_code == 202
    body = response.json()
    execution_id = uuid.UUID(body["id"])
    assert body["workflow_id"] == str(workflow_id)
    assert body["status"] == "QUEUED"

    [execution] = await _executions(db_session, workflow_id)
    assert execution.id == execution_id
    assert execution.status == "QUEUED"
    assert execution.input == {"order_id": 42, "items": [{"sku": "A1"}]}
    assert (execution.started_at, execution.finished_at) == (None, None)
    steps = await _steps(db_session, execution_id)
    assert [(s.position, s.name, s.type, s.status, s.attempt_count) for s in steps] == [
        (0, "fetch", "http", "PENDING", 0),
        (1, "wait", "delay", "PENDING", 0),
        (2, "note", "demo", "PENDING", 0),
    ]
    assert await _log_events(db_session, execution_id) == [("INFO", "execution_created")]

    # Exactly one message, carrying only the execution ID (no definition, no input).
    raw_messages = await test_redis.lrange(queue_key, 0, -1)
    assert raw_messages == [f'{{"execution_id": "{execution_id}"}}'.encode()]


async def test_snapshot_is_isolated_from_later_workflow_changes(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    workflow_id = await _workflow_id(client)
    stored_definition = (await client.get(f"/api/v1/workflows/{workflow_id}")).json()["definition"]
    first = uuid.UUID((await _execute(client, workflow_id)).json()["id"])

    # No update endpoint exists yet; change the stored definition directly.
    changed = {"steps": [{"name": "only", "type": "demo", "config": {"message": "v2"}}]}
    await db_session.execute(update(Workflow).where(Workflow.id == workflow_id).values(definition=changed))
    await db_session.commit()
    second = uuid.UUID((await _execute(client, workflow_id)).json()["id"])

    db_session.expunge_all()
    first_execution = await db_session.get(Execution, first)
    second_execution = await db_session.get(Execution, second)
    assert first_execution is not None and second_execution is not None
    assert first_execution.definition_snapshot == stored_definition
    assert [s.name for s in await _steps(db_session, first)] == ["fetch", "wait", "note"]
    assert second_execution.definition_snapshot == changed
    assert [s.name for s in await _steps(db_session, second)] == ["only"]


async def test_execute_without_body_stores_empty_input(client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    workflow_id = await _workflow_id(client)

    response = await _execute(client, workflow_id)

    assert response.status_code == 202
    [execution] = await _executions(db_session, workflow_id)
    assert execution.input == {}


async def test_input_is_stored_verbatim_as_data(client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    workflow_id = await _workflow_id(client)
    payload = {"cmd": "$(rm -rf /)", "sql": "'; DROP TABLE executions; --", "unicode": "héllo ✓", "n": None, "f": 1.5}

    assert (await _execute(client, workflow_id, {"input": payload})).status_code == 202

    [execution] = await _executions(db_session, workflow_id)
    assert execution.input == payload


async def test_unknown_workflow_returns_404_and_creates_nothing(
    client: httpx.AsyncClient, db_session: AsyncSession, test_redis: Redis, queue_key: str
) -> None:
    before = await _total(db_session, Execution)
    missing = uuid.uuid4()

    response = await _execute(client, missing, {"input": {"a": 1}})

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "workflow_not_found", "message": f"Workflow {missing} not found"}}
    assert await _total(db_session, Execution) == before
    assert await test_redis.llen(queue_key) == 0


@pytest.mark.parametrize(
    "body",
    [{"input": [1]}, {"input": {}, "extra": 1}, {"input": {"x": "a\u0000b"}}],
    ids=["list", "extra-field", "nul"],
)
async def test_invalid_input_returns_422_and_creates_nothing(
    client: httpx.AsyncClient, db_session: AsyncSession, test_redis: Redis, queue_key: str, body: dict
) -> None:
    workflow_id = await _workflow_id(client)

    response = await _execute(client, workflow_id, body)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert await _executions(db_session, workflow_id) == []
    assert await test_redis.llen(queue_key) == 0


async def test_repeated_requests_create_separate_executions_in_fifo_order(
    client: httpx.AsyncClient, db_session: AsyncSession, test_redis: Redis, queue_key: str
) -> None:
    workflow_id = await _workflow_id(client)

    ids = [uuid.UUID((await _execute(client, workflow_id, {"input": {"n": 1}})).json()["id"]) for _ in range(3)]

    assert len(set(ids)) == 3
    assert {e.id for e in await _executions(db_session, workflow_id)} == set(ids)
    assert await _queued_ids(test_redis, queue_key) == ids
    assert decode_message(await test_redis.rpop(queue_key)) == ids[0]  # what a worker would pop first


async def test_enqueue_failure_marks_execution_failed_and_returns_503(
    client: httpx.AsyncClient, db_session: AsyncSession, test_redis: Redis, queue_key: str, unreachable_queue: None
) -> None:
    workflow_id = await _workflow_id(client)

    response = await _execute(client, workflow_id, {"input": {"a": 1}})

    assert response.status_code == 503
    [execution] = await _executions(db_session, workflow_id)
    assert response.json() == {
        "error": {
            "code": "execution_queue_unavailable",
            "message": f"Execution {execution.id} could not be queued and was marked FAILED. Try again later.",
        }
    }
    for leaked in ("127.0.0.1", "Connection refused", "redis://", "Traceback"):
        assert leaked not in response.text
    assert execution.status == "FAILED"
    assert execution.finished_at is not None and execution.started_at is None
    assert {s.status for s in await _steps(db_session, execution.id)} == {"SKIPPED"}
    assert await _log_events(db_session, execution.id) == [("INFO", "execution_created"), ("ERROR", "enqueue_failed")]
    assert await test_redis.llen(queue_key) == 0


async def test_persistence_failure_returns_503_and_leaves_nothing(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    test_redis: Redis,
    queue_key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_id = await _workflow_id(client)
    before = {model: await _total(db_session, model) for model in (Execution, ExecutionStep, ExecutionLog)}
    real_commit = db_session.commit

    async def failing_commit() -> None:
        raise OperationalError("COMMIT", {}, ConnectionResetError("connection lost"))

    monkeypatch.setattr(db_session, "commit", failing_commit)
    response = await _execute(client, workflow_id, {"input": {"a": 1}})
    monkeypatch.setattr(db_session, "commit", real_commit)

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "execution_persistence_failed",
            "message": "The execution could not be saved and was not queued. Try again later.",
        }
    }
    assert "connection lost" not in response.text and "COMMIT" not in response.text
    # The flushed rows were rolled back and nothing reached Redis.
    assert {model: await _total(db_session, model) for model in before} == before
    assert await test_redis.llen(queue_key) == 0
    # The session is usable again afterwards.
    assert (await _execute(client, workflow_id)).status_code == 202
    assert await test_redis.llen(queue_key) == 1


async def test_enqueue_failure_when_marking_failed_also_fails(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    queue_key: str,
    unreachable_queue: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If PostgreSQL also fails after Redis did, the response must not claim the
    execution was marked FAILED: it stays QUEUED without a message (known limitation)."""
    workflow_id = await _workflow_id(client)
    real_commit = db_session.commit
    commits = 0

    async def second_commit_fails() -> None:
        nonlocal commits
        commits += 1
        if commits == 2:
            raise OperationalError("COMMIT", {}, ConnectionResetError("connection lost"))
        await real_commit()

    monkeypatch.setattr(db_session, "commit", second_commit_fails)
    response = await _execute(client, workflow_id)
    monkeypatch.setattr(db_session, "commit", real_commit)

    assert response.status_code == 503
    [execution] = await _executions(db_session, workflow_id)
    assert response.json()["error"] == {
        "code": "execution_queue_unavailable",
        "message": f"Execution {execution.id} could not be queued. Try again later.",
    }
    assert execution.status == "QUEUED"
    assert await _log_events(db_session, execution.id) == [("INFO", "execution_created")]

