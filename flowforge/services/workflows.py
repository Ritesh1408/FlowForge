"""Workflow registry: creation, validation and retrieval of workflow definitions."""

import logging
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from flowforge.core.errors import WorkflowNameConflictError, WorkflowNotFoundError
from flowforge.models import Workflow
from flowforge.repositories import workflows as workflow_repo
from flowforge.schemas.workflows import WorkflowCreate

logger = logging.getLogger(__name__)

WORKFLOW_NAME_CONSTRAINT = "uq_workflows_name"


def _violated_constraint(exc: IntegrityError) -> str | None:
    # The asyncpg driver error (chained as the DBAPI error's cause) names the constraint.
    return getattr(exc.orig.__cause__, "constraint_name", None)


class WorkflowService:
    """Business logic for the registry. Definitions arrive already validated by
    ``WorkflowCreate``; only validated definitions are ever persisted."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, data: WorkflowCreate) -> Workflow:
        try:
            workflow = await workflow_repo.create_workflow(
                self._session,
                name=data.name,
                description=data.description,
                # Store the normalized form (defaults filled in) the executor will read.
                definition=data.definition.model_dump(mode="json"),
            )
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            if _violated_constraint(exc) == WORKFLOW_NAME_CONSTRAINT:
                raise WorkflowNameConflictError(f"A workflow named {data.name!r} already exists") from exc
            raise
        logger.info("Workflow created: id=%s name=%r", workflow.id, workflow.name)
        return workflow

    async def get(self, workflow_id: uuid.UUID) -> Workflow:
        workflow = await workflow_repo.get_workflow(self._session, workflow_id)
        if workflow is None:
            raise WorkflowNotFoundError(f"Workflow {workflow_id} not found")
        return workflow

    async def list(self, *, limit: int, offset: int) -> list[Workflow]:
        return await workflow_repo.list_workflows(self._session, limit=limit, offset=offset)
