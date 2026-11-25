import copy
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowforge.models import (
    Execution,
    ExecutionLog,
    ExecutionStatus,
    ExecutionStep,
    StepStatus,
    Workflow,
)


# Default for optional update arguments: "leave unchanged", as opposed to None ("clear").
_UNSET: Any = object()


async def create_execution(
    session: AsyncSession, workflow: Workflow, *, input_data: dict[str, Any] | None = None
) -> tuple[Execution, list[ExecutionStep]]:
    """Create an execution, its definition snapshot and one PENDING step per defined step.

    ``workflow.definition`` must already be valid: definitions are validated by the
    workflow registry (``flowforge.schemas.workflow_definition``) before they are stored.
    All rows are written in the caller's transaction: if any insert fails, rolling back
    leaves neither the execution nor any of its steps.
    """
    snapshot = copy.deepcopy(workflow.definition)

    execution = Execution(
        id=uuid.uuid4(),
        workflow_id=workflow.id,
        definition_snapshot=snapshot,
        status=ExecutionStatus.QUEUED.value,
        input=input_data or {},
    )
    steps = [
        ExecutionStep(
            execution_id=execution.id,
            position=position,
            name=spec["name"],
            type=spec["type"],
            status=StepStatus.PENDING.value,
        )
        for position, spec in enumerate(snapshot["steps"])
    ]
    session.add(execution)
    session.add_all(steps)
    await session.flush()
    return execution, steps


async def update_execution_status(
    session: AsyncSession,
    execution_id: uuid.UUID,
    status: ExecutionStatus | str,
    *,
    started_at: datetime | None = _UNSET,
    finished_at: datetime | None = _UNSET,
) -> Execution:
    """Set an execution's status. Transition rules are not checked here."""
    execution = await session.get(Execution, execution_id)
    if execution is None:
        raise LookupError(f"Execution {execution_id} not found")
    execution.status = ExecutionStatus(status).value
    if started_at is not _UNSET:
        execution.started_at = started_at
    if finished_at is not _UNSET:
        execution.finished_at = finished_at
    await session.flush()
    return execution


async def update_step_status(
    session: AsyncSession,
    step_id: uuid.UUID,
    status: StepStatus | str,
    *,
    attempt_count: int = _UNSET,
    output: dict[str, Any] | None = _UNSET,
    error: str | None = _UNSET,
    started_at: datetime | None = _UNSET,
    finished_at: datetime | None = _UNSET,
) -> ExecutionStep:
    """Set a step's status and, optionally, its result fields. Transitions are not checked."""
    step = await session.get(ExecutionStep, step_id)
    if step is None:
        raise LookupError(f"Execution step {step_id} not found")
    step.status = StepStatus(status).value
    changes = {
        "attempt_count": attempt_count,
        "output": output,
        "error": error,
        "started_at": started_at,
        "finished_at": finished_at,
    }
    for column, value in changes.items():
        if value is not _UNSET:
            setattr(step, column, value)
    await session.flush()
    return step


async def add_log(
    session: AsyncSession,
    execution_id: uuid.UUID,
    *,
    level: str,
    event: str,
    message: str,
    step_id: uuid.UUID | None = None,
    data: dict[str, Any] | None = None,
) -> ExecutionLog:
    log = ExecutionLog(
        execution_id=execution_id,
        step_id=step_id,
        level=level,
        event=event,
        message=message,
        data=data,
    )
    session.add(log)
    await session.flush()
    return log


async def list_logs(session: AsyncSession, execution_id: uuid.UUID) -> list[ExecutionLog]:
    """An execution's log entries, oldest first (uses the (execution_id, created_at) index)."""
    statement = (
        select(ExecutionLog)
        .where(ExecutionLog.execution_id == execution_id)
        .order_by(ExecutionLog.created_at, ExecutionLog.id)
    )
    return list((await session.scalars(statement)).all())
