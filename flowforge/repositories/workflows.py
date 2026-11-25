import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowforge.models import Workflow


async def create_workflow(
    session: AsyncSession, *, name: str, definition: dict[str, Any], description: str | None = None
) -> Workflow:
    workflow = Workflow(name=name, definition=definition, description=description)
    session.add(workflow)
    await session.flush()
    return workflow


async def get_workflow(session: AsyncSession, workflow_id: uuid.UUID) -> Workflow | None:
    return await session.get(Workflow, workflow_id)


async def list_workflows(session: AsyncSession, *, limit: int = 50, offset: int = 0) -> list[Workflow]:
    """Workflows oldest first, for offset paging.

    (created_at, id) is a total order (id is unique), so every query returns the same
    sequence and pages neither overlap nor skip rows. The registry creates one workflow
    per transaction, so created_at follows creation order; rows sharing a created_at
    (several inserted in one transaction) fall back to id order, which is arbitrary but fixed.
    """
    statement = (
        select(Workflow).order_by(Workflow.created_at, Workflow.id).limit(limit).offset(offset)
    )
    return list((await session.scalars(statement)).all())
