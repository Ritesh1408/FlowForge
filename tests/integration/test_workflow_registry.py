"""Workflow registry API against the real flowforge_test database.

Each test runs in the rolled-back ``db_session`` transaction; the app's session
dependency is overridden to use it, so service commits are savepoint releases.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from flowforge.core.config import Settings
from flowforge.db.session import get_session
from flowforge.main import create_app
from flowforge.models import ExecutionStep, Workflow
from flowforge.repositories import executions as execution_repo
from flowforge.repositories import workflows as workflow_repo

pytestmark = pytest.mark.integration

DEFINITION = {
    "steps": [
        {"name": "fetch", "type": "http", "config": {"url": "https://example.com/orders", "method": "get"}},
        {"name": "wait", "type": "delay", "config": {"seconds": 2}},
        {"name": "note", "type": "demo", "config": {"message": "done"}},
    ]
}
NORMALIZED = {
    "steps": [
        {
            "name": "fetch",
            "type": "http",
            "config": {
                "url": "https://example.com/orders",
                "method": "GET",
                "headers": {},
                "body": None,
                "timeout_seconds": 10.0,
            },
        },
        {"name": "wait", "type": "delay", "config": {"seconds": 2.0}},
        {"name": "note", "type": "demo", "config": {"message": "done"}},
    ]
}


@pytest.fixture
async def client(live_app_settings: Settings, db_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(live_app_settings)

    async def session_override() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_session] = session_override
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def _workflow_count(session: AsyncSession) -> int:
    return (await session.execute(select(func.count()).select_from(Workflow))).scalar_one()


async def _create(client: httpx.AsyncClient, name: str, **extra: object) -> httpx.Response:
    return await client.post("/api/v1/workflows", json={"name": name, "definition": DEFINITION, **extra})


async def test_create_persists_normalized_definition(client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    response = await _create(client, "  orders  ", description="Order sync")

    assert response.status_code == 201
    body = response.json()
    assert (body["name"], body["description"], body["definition"]) == ("orders", "Order sync", NORMALIZED)
    assert body["created_at"] and body["updated_at"]

    db_session.expunge_all()
    stored = await workflow_repo.get_workflow(db_session, uuid.UUID(body["id"]))
    assert stored is not None
    assert (stored.name, stored.description, stored.definition) == ("orders", "Order sync", NORMALIZED)


async def test_get_returns_created_workflow(client: httpx.AsyncClient) -> None:
    created = (await _create(client, "orders")).json()

    response = await client.get(f"/api/v1/workflows/{created['id']}")

    assert response.status_code == 200
    assert response.json() == created


async def test_get_nonexistent_returns_404(client: httpx.AsyncClient) -> None:
    await _create(client, "orders")
    missing = uuid.uuid4()

    response = await client.get(f"/api/v1/workflows/{missing}")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "workflow_not_found", "message": f"Workflow {missing} not found"}}


async def test_duplicate_name_returns_409_without_internals(client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    first = await _create(client, "orders")
    second = await _create(client, "orders")

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json() == {
        "error": {"code": "workflow_name_conflict", "message": "A workflow named 'orders' already exists"}
    }
    for leaked in ("uq_workflows_name", "duplicate key", "INSERT", "asyncpg", "IntegrityError"):
        assert leaked not in second.text
    assert await _workflow_count(db_session) == 1
    # The session is still usable after the rolled-back insert.
    assert (await _create(client, "orders-2")).status_code == 201


@pytest.mark.parametrize(
    "definition",
    [
        {"steps": []},
        {"steps": [{"name": "a"}]},
        {"steps": [{"name": "run", "type": "shell", "config": {"command": "whoami"}}]},
        {"steps": [{"name": "h", "type": "http", "config": {"url": "http://127.0.0.1:5432/"}}]},
        {"steps": [{"name": "d", "type": "delay", "config": {"seconds": 100000}}]},
    ],
    ids=["empty", "no-type", "shell", "ssrf", "delay-too-long"],
)
async def test_invalid_definition_is_not_stored(
    client: httpx.AsyncClient, db_session: AsyncSession, definition: dict
) -> None:
    before = await _workflow_count(db_session)

    response = await client.post("/api/v1/workflows", json={"name": "bad", "definition": definition})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert await _workflow_count(db_session) == before


async def test_list_order_is_deterministic_and_pages_are_stable(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    ids = [uuid.UUID((await _create(client, f"wf-{i}")).json()["id"]) for i in range(5)]
    # All rows here share one outer transaction, hence one now(). Give three of them
    # distinct times (as separate requests would have) and leave two tied.
    base = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
    times = {ids[0]: base + timedelta(seconds=3), ids[1]: base, ids[2]: base + timedelta(seconds=1),
             ids[3]: base + timedelta(seconds=1), ids[4]: base + timedelta(seconds=2)}
    for workflow_id, created_at in times.items():
        await db_session.execute(update(Workflow).where(Workflow.id == workflow_id).values(created_at=created_at))
    await db_session.commit()

    expected = [str(i) for i in sorted(ids, key=lambda i: (times[i], i))]

    full = (await client.get("/api/v1/workflows?limit=100")).json()
    listed = [item["id"] for item in full["items"]]
    assert [i for i in listed if i in expected] == expected  # creation time, then id for ties
    assert (await client.get("/api/v1/workflows?limit=100")).json() == full  # repeatable

    paged: list[str] = []
    for offset in range(0, len(listed) + 2, 2):
        page = (await client.get(f"/api/v1/workflows?limit=2&offset={offset}")).json()
        assert (page["limit"], page["offset"]) == (2, offset)
        paged += [item["id"] for item in page["items"]]
    assert paged == listed  # no overlap, no gaps

    assert (await client.get(f"/api/v1/workflows?offset={len(listed)}")).json()["items"] == []


async def test_registered_workflow_can_seed_an_execution(client: httpx.AsyncClient, db_session: AsyncSession) -> None:
    """The executions repository relies on registry-validated definitions."""
    created = (await _create(client, "orders")).json()
    workflow = await workflow_repo.get_workflow(db_session, uuid.UUID(created["id"]))
    assert workflow is not None

    execution, _ = await execution_repo.create_execution(db_session, workflow)

    steps = (
        await db_session.scalars(
            select(ExecutionStep).where(ExecutionStep.execution_id == execution.id).order_by(ExecutionStep.position)
        )
    ).all()
    assert [(s.position, s.name, s.type) for s in steps] == [(0, "fetch", "http"), (1, "wait", "delay"), (2, "note", "demo")]
    assert execution.definition_snapshot == NORMALIZED
