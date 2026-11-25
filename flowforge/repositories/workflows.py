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
    statement = (
        select(Workflow).order_by(Workflow.created_at, Workflow.id).limit(limit).offset(offset)
    )
    return list((await session.scalars(statement)).all())
