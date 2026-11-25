import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from flowforge.db.session import get_session
from flowforge.schemas.errors import ErrorResponse
from flowforge.schemas.workflows import WorkflowCreate, WorkflowList, WorkflowResponse
from flowforge.services.workflows import WorkflowService

router = APIRouter(prefix="/workflows", tags=["workflows"])

VALIDATION_ERROR = {status.HTTP_422_UNPROCESSABLE_CONTENT: {"model": ErrorResponse}}


def get_workflow_service(session: AsyncSession = Depends(get_session)) -> WorkflowService:
    return WorkflowService(session)


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=WorkflowResponse,
    responses={status.HTTP_409_CONFLICT: {"model": ErrorResponse}, **VALIDATION_ERROR},
)
async def create_workflow(
    body: WorkflowCreate, response: Response, service: WorkflowService = Depends(get_workflow_service)
) -> WorkflowResponse:
    workflow = await service.create(body)
    response.headers["Location"] = f"/api/v1/workflows/{workflow.id}"
    return WorkflowResponse.model_validate(workflow)


@router.get("", response_model=WorkflowList, responses=VALIDATION_ERROR)
async def list_workflows(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: WorkflowService = Depends(get_workflow_service),
) -> WorkflowList:
    workflows = await service.list(limit=limit, offset=offset)
    return WorkflowList(
        items=[WorkflowResponse.model_validate(w) for w in workflows], limit=limit, offset=offset
    )


@router.get(
    "/{workflow_id}",
    response_model=WorkflowResponse,
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorResponse}, **VALIDATION_ERROR},
)
async def get_workflow(
    workflow_id: uuid.UUID, service: WorkflowService = Depends(get_workflow_service)
) -> WorkflowResponse:
    return WorkflowResponse.model_validate(await service.get(workflow_id))
