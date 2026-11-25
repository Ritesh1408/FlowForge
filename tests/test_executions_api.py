"""API-layer tests for POST /api/v1/workflows/{id}/execute with a fake service (no database).

They check input validation and bounds, status codes and the error envelope, and that
invalid requests never reach the service (and therefore never reach persistence or Redis).
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from flowforge.api.v1.workflows import get_execution_service
from flowforge.core.config import Settings
from flowforge.core.errors import (
    ExecutionPersistenceError,
    ExecutionQueueUnavailableError,
    WorkflowNotFoundError,
)
from flowforge.main import create_app
from flowforge.schemas.executions import MAX_INPUT_BYTES, MAX_INPUT_DEPTH, ExecutionCreate


class FakeExecutionService:
    def __init__(self) -> None:
        self.calls: list[tuple[uuid.UUID, dict[str, Any]]] = []
        self.fail_with: Exception | None = None

    async def create(self, workflow_id: uuid.UUID, input_data: dict[str, Any]) -> Any:
        if self.fail_with:
            raise self.fail_with
        self.calls.append((workflow_id, input_data))
        return SimpleNamespace(
            id=uuid.uuid4(),
            workflow_id=workflow_id,
            status="QUEUED",
            created_at=datetime(2026, 11, 25, tzinfo=UTC),
            input=input_data,
        )


@pytest.fixture
def service() -> FakeExecutionService:
    return FakeExecutionService()


@pytest.fixture
async def client(unit_settings: Settings, service: FakeExecutionService):
    app = create_app(unit_settings)
    app.dependency_overrides[get_execution_service] = lambda: service
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


def _url(workflow_id: uuid.UUID | str) -> str:
    return f"/api/v1/workflows/{workflow_id}/execute"


def _nested(depth: int) -> dict[str, Any]:
    """An input object whose container nesting depth is exactly ``depth``."""
    value: dict[str, Any] = {}
    for _ in range(depth - 1):
        value = {"a": value}
    return value


async def test_execute_returns_202_with_execution_summary(
    client: httpx.AsyncClient, service: FakeExecutionService
) -> None:
    workflow_id = uuid.uuid4()

    response = await client.post(_url(workflow_id), json={"input": {"order_id": 42, "tags": ["a"]}})

    assert response.status_code == 202
    body = response.json()
    assert set(body) == {"id", "workflow_id", "status", "created_at"}
    assert body["workflow_id"] == str(workflow_id)
    assert body["status"] == "QUEUED"
    assert "location" not in response.headers
    assert service.calls == [(workflow_id, {"order_id": 42, "tags": ["a"]})]


@pytest.mark.parametrize("kwargs", [{}, {"json": {}}, {"json": {"input": {}}}], ids=["no-body", "empty", "empty-input"])
async def test_input_defaults_to_empty_object(
    client: httpx.AsyncClient, service: FakeExecutionService, kwargs: dict[str, Any]
) -> None:
    response = await client.post(_url(uuid.uuid4()), **kwargs)

    assert response.status_code == 202
    assert service.calls[0][1] == {}


@pytest.mark.parametrize(
    "content",
    [
        '{"input": [1, 2]}',
        '{"input": "text"}',
        '{"input": null}',
        '{"input": {}, "priority": 1}',
        "[]",
        "not json",
        '{"input": {"x": NaN}}',
        '{"input": {"x": Infinity}}',
        '{"input": {"x": "a\\u0000b"}}',
        '{"input": {"a\\u0000": 1}}',
    ],
    ids=["list", "string", "null", "extra-field", "array-body", "malformed", "nan", "infinity", "nul-value", "nul-key"],
)
async def test_invalid_input_returns_422_and_skips_service(
    client: httpx.AsyncClient, service: FakeExecutionService, content: str
) -> None:
    response = await client.post(_url(uuid.uuid4()), content=content, headers={"content-type": "application/json"})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert service.calls == []


async def test_invalid_workflow_id_returns_422(client: httpx.AsyncClient, service: FakeExecutionService) -> None:
    response = await client.post(_url("not-a-uuid"), json={})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert service.calls == []


async def test_validation_error_does_not_echo_input(client: httpx.AsyncClient) -> None:
    secret = "s3cr3t-token-value"

    response = await client.post(_url(uuid.uuid4()), json={"input": {"t": secret}, "extra": secret})

    assert response.status_code == 422
    assert secret not in response.text


def test_input_depth_limit_is_inclusive() -> None:
    assert ExecutionCreate(input=_nested(MAX_INPUT_DEPTH)).input == _nested(MAX_INPUT_DEPTH)
    assert ExecutionCreate(input={"l": [[[[[[[[[1]]]]]]]]]}).input  # dict + 9 lists = depth 10
    with pytest.raises(ValueError, match="nesting"):
        ExecutionCreate(input=_nested(MAX_INPUT_DEPTH + 1))
    with pytest.raises(ValueError, match="nesting"):
        ExecutionCreate(input={"l": [[[[[[[[[[1]]]]]]]]]]})


def test_input_size_limit() -> None:
    overhead = len('{"k":""}')
    fits = {"k": "x" * (MAX_INPUT_BYTES - overhead)}
    assert ExecutionCreate(input=fits).input == fits
    with pytest.raises(ValueError, match="bytes"):
        ExecutionCreate(input={"k": "x" * (MAX_INPUT_BYTES - overhead + 1)})
    # Measured in UTF-8 bytes, not characters.
    with pytest.raises(ValueError, match="bytes"):
        ExecutionCreate(input={"k": "é" * (MAX_INPUT_BYTES // 2)})


async def test_oversized_input_returns_422(client: httpx.AsyncClient, service: FakeExecutionService) -> None:
    response = await client.post(_url(uuid.uuid4()), json={"input": {"k": "x" * (MAX_INPUT_BYTES + 1)}})

    assert response.status_code == 422
    assert service.calls == []


async def test_workflow_not_found_returns_404_envelope(
    client: httpx.AsyncClient, service: FakeExecutionService
) -> None:
    missing = uuid.uuid4()
    service.fail_with = WorkflowNotFoundError(f"Workflow {missing} not found")

    response = await client.post(_url(missing), json={})

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "workflow_not_found", "message": f"Workflow {missing} not found"}}


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ExecutionQueueUnavailableError("Execution x could not be queued. Try again later."), "execution_queue_unavailable"),
        (ExecutionPersistenceError("The execution could not be saved and was not queued."), "execution_persistence_failed"),
    ],
    ids=["queue", "persistence"],
)
async def test_service_unavailable_errors_return_503_envelope(
    client: httpx.AsyncClient, service: FakeExecutionService, error: Exception, code: str
) -> None:
    service.fail_with = error

    response = await client.post(_url(uuid.uuid4()), json={})

    assert response.status_code == 503
    assert response.json() == {"error": {"code": code, "message": error.message}}
