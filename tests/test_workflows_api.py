"""API-layer tests for /api/v1/workflows with a fake service (no database).

They check request validation, status codes and the error envelope, and that invalid
definitions never reach the service (and therefore never reach persistence).
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from flowforge.api.v1.workflows import get_workflow_service
from flowforge.core.config import Settings
from flowforge.core.errors import WorkflowNameConflictError, WorkflowNotFoundError
from flowforge.main import create_app
from flowforge.schemas.workflows import WorkflowCreate

VALID_BODY = {
    "name": "orders",
    "definition": {"steps": [{"name": "wait", "type": "delay", "config": {"seconds": 1}}]},
}


class FakeWorkflowService:
    def __init__(self) -> None:
        self.created: list[WorkflowCreate] = []
        self.list_calls: list[dict[str, int]] = []
        self.fail_with: Exception | None = None

    @staticmethod
    def _row(data: WorkflowCreate) -> SimpleNamespace:
        now = datetime(2026, 11, 25, tzinfo=UTC)
        return SimpleNamespace(
            id=uuid.uuid4(),
            name=data.name,
            description=data.description,
            definition=data.definition.model_dump(mode="json"),
            created_at=now,
            updated_at=now,
        )

    async def create(self, data: WorkflowCreate) -> Any:
        if self.fail_with:
            raise self.fail_with
        self.created.append(data)
        return self._row(data)

    async def get(self, workflow_id: uuid.UUID) -> Any:
        raise WorkflowNotFoundError(f"Workflow {workflow_id} not found")

    async def list(self, *, limit: int, offset: int) -> list[Any]:
        self.list_calls.append({"limit": limit, "offset": offset})
        return []


@pytest.fixture
def service() -> FakeWorkflowService:
    return FakeWorkflowService()


@pytest.fixture
async def client(unit_settings: Settings, service: FakeWorkflowService):
    app = create_app(unit_settings)
    app.dependency_overrides[get_workflow_service] = lambda: service
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def test_create_returns_201_with_location(client: httpx.AsyncClient, service: FakeWorkflowService) -> None:
    response = await client.post("/api/v1/workflows", json=VALID_BODY)

    assert response.status_code == 201
    body = response.json()
    assert response.headers["location"] == f"/api/v1/workflows/{body['id']}"
    assert body["name"] == "orders" and body["description"] is None
    assert body["definition"]["steps"][0] == {"name": "wait", "type": "delay", "config": {"seconds": 1.0}}
    assert len(service.created) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"definition": VALID_BODY["definition"]},
        {"name": "   ", "definition": VALID_BODY["definition"]},
        {"name": "x" * 201, "definition": VALID_BODY["definition"]},
        {"name": "orders"},
        {"name": "orders", "definition": {"steps": []}},
        {"name": "orders", "definition": {"steps": [{"name": "s", "type": "shell", "config": {"cmd": "ls"}}]}},
        {"name": "orders", "definition": {"steps": [{"name": "h", "type": "http", "config": {"url": "http://localhost/"}}]}},
        {**VALID_BODY, "id": str(uuid.uuid4())},
        [],
    ],
    ids=[
        "no-name", "blank-name", "long-name", "no-definition", "empty-steps", "unsupported-type",
        "ssrf-url", "client-supplied-id", "not-an-object",
    ],
)
async def test_invalid_create_returns_422_and_is_not_persisted(
    client: httpx.AsyncClient, service: FakeWorkflowService, body: Any
) -> None:
    response = await client.post("/api/v1/workflows", json=body)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"] and all({"loc", "msg", "type"} == set(d) for d in error["details"])
    assert service.created == []


async def test_malformed_json_returns_422(client: httpx.AsyncClient, service: FakeWorkflowService) -> None:
    response = await client.post(
        "/api/v1/workflows", content=b'{"name": "x", "definition": ', headers={"content-type": "application/json"}
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert service.created == []


async def test_validation_error_does_not_echo_input(client: httpx.AsyncClient) -> None:
    secret = "token-should-not-be-echoed"
    body = {"name": "orders", "definition": {"steps": [{"name": "h", "type": "http", "config": {
        "url": "http://10.0.0.5/", "headers": {"Authorization": secret}}}]}}

    response = await client.post("/api/v1/workflows", json=body)

    assert response.status_code == 422
    assert secret not in response.text
    detail = response.json()["error"]["details"][0]
    assert detail["loc"] == ["body", "definition", "steps", 0, "http", "config", "url"]


async def test_name_conflict_returns_409(client: httpx.AsyncClient, service: FakeWorkflowService) -> None:
    service.fail_with = WorkflowNameConflictError("A workflow named 'orders' already exists")

    response = await client.post("/api/v1/workflows", json=VALID_BODY)

    assert response.status_code == 409
    assert response.json() == {
        "error": {"code": "workflow_name_conflict", "message": "A workflow named 'orders' already exists"}
    }


async def test_get_unknown_id_returns_404(client: httpx.AsyncClient) -> None:
    workflow_id = uuid.uuid4()
    response = await client.get(f"/api/v1/workflows/{workflow_id}")

    assert response.status_code == 404
    assert response.json() == {"error": {"code": "workflow_not_found", "message": f"Workflow {workflow_id} not found"}}


@pytest.mark.parametrize("bad_id", ["not-a-uuid", "123", "00000000-0000-0000-0000-00000000000g"])
async def test_get_invalid_id_returns_422(client: httpx.AsyncClient, bad_id: str) -> None:
    response = await client.get(f"/api/v1/workflows/{bad_id}")

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["loc"] == ["path", "workflow_id"]


async def test_list_defaults(client: httpx.AsyncClient, service: FakeWorkflowService) -> None:
    response = await client.get("/api/v1/workflows")

    assert response.status_code == 200
    assert response.json() == {"items": [], "limit": 50, "offset": 0}
    assert service.list_calls == [{"limit": 50, "offset": 0}]


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "limit=abc", "offset=-1"])
async def test_list_rejects_invalid_paging(client: httpx.AsyncClient, service: FakeWorkflowService, query: str) -> None:
    response = await client.get(f"/api/v1/workflows?{query}")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert service.list_calls == []


async def test_unknown_route_and_method_use_error_envelope(client: httpx.AsyncClient) -> None:
    missing = await client.get("/api/v1/nope")
    wrong_method = await client.delete("/api/v1/workflows")

    assert (missing.status_code, missing.json()["error"]["code"]) == (404, "not_found")
    assert (wrong_method.status_code, wrong_method.json()["error"]["code"]) == (405, "method_not_allowed")
    assert "allow" in wrong_method.headers
