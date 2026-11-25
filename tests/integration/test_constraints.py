"""Database-level constraints, exercised with raw inserts so the DB itself is tested."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from flowforge.models import Workflow
from flowforge.repositories import executions as execution_repo
from flowforge.repositories import workflows as workflow_repo

pytestmark = pytest.mark.integration

DEFINITION = {"steps": [{"name": "fetch", "type": "http"}, {"name": "wait", "type": "delay"}]}


async def _expect_violation(session: AsyncSession, sql: str, params: dict, constraint: str) -> None:
    with pytest.raises(IntegrityError) as excinfo:
        async with session.begin_nested():
            await session.execute(text(sql), params)
    assert constraint in str(excinfo.value.orig)


async def _workflow(session: AsyncSession, name: str = "constraints") -> Workflow:
    return await workflow_repo.create_workflow(session, name=name, definition=DEFINITION)


async def test_unique_workflow_name(db_session: AsyncSession) -> None:
    await _workflow(db_session, "same-name")
    with pytest.raises(IntegrityError) as excinfo:
        async with db_session.begin_nested():
            await workflow_repo.create_workflow(db_session, name="same-name", definition=DEFINITION)
    assert "uq_workflows_name" in str(excinfo.value.orig)


async def test_execution_requires_existing_workflow(db_session: AsyncSession) -> None:
    await _expect_violation(
        db_session,
        "INSERT INTO executions (id, workflow_id, definition_snapshot) VALUES (:id, :wf, '{}')",
        {"id": uuid.uuid4(), "wf": uuid.uuid4()},
        "fk_executions_workflow_id_workflows",
    )


async def test_step_requires_existing_execution(db_session: AsyncSession) -> None:
    await _expect_violation(
        db_session,
        "INSERT INTO execution_steps (id, execution_id, position, name, type) VALUES (:id, :ex, 0, 'a', 'delay')",
        {"id": uuid.uuid4(), "ex": uuid.uuid4()},
        "fk_execution_steps_execution_id_executions",
    )


async def test_log_requires_existing_execution_and_step(db_session: AsyncSession) -> None:
    execution, _ = await execution_repo.create_execution(db_session, await _workflow(db_session))
    insert_log = (
        "INSERT INTO execution_logs (execution_id, step_id, level, event, message) "
        "VALUES (:ex, :step, 'INFO', 'e', 'm')"
    )
    await _expect_violation(
        db_session, insert_log, {"ex": uuid.uuid4(), "step": None}, "fk_execution_logs_execution_id_executions"
    )
    await _expect_violation(
        db_session, insert_log, {"ex": execution.id, "step": uuid.uuid4()}, "fk_execution_logs_step_id_execution_steps"
    )


async def test_workflow_with_executions_cannot_be_deleted(db_session: AsyncSession) -> None:
    workflow = await _workflow(db_session)
    await execution_repo.create_execution(db_session, workflow)
    await _expect_violation(
        db_session, "DELETE FROM workflows WHERE id = :id", {"id": workflow.id}, "fk_executions_workflow_id_workflows"
    )


async def test_unique_step_position_per_execution(db_session: AsyncSession) -> None:
    workflow = await _workflow(db_session)
    first, _ = await execution_repo.create_execution(db_session, workflow)
    second, _ = await execution_repo.create_execution(db_session, workflow)
    insert_step = (
        "INSERT INTO execution_steps (id, execution_id, position, name, type) VALUES (:id, :ex, 0, 'dup', 'delay')"
    )
    await _expect_violation(
        db_session, insert_step, {"id": uuid.uuid4(), "ex": first.id}, "uq_execution_steps_execution_id_position"
    )
    # The same position in a different execution is fine.
    async with db_session.begin_nested():
        await db_session.execute(
            text("UPDATE execution_steps SET position = position + 10 WHERE execution_id = :ex"), {"ex": second.id}
        )
        await db_session.execute(text(insert_step), {"id": uuid.uuid4(), "ex": second.id})


async def test_invalid_execution_status_rejected(db_session: AsyncSession) -> None:
    execution, _ = await execution_repo.create_execution(db_session, await _workflow(db_session))
    await _expect_violation(
        db_session,
        "UPDATE executions SET status = 'PENDING' WHERE id = :id",  # a step status, not an execution one
        {"id": execution.id},
        "ck_executions_status",
    )


async def test_invalid_step_status_rejected(db_session: AsyncSession) -> None:
    _, steps = await execution_repo.create_execution(db_session, await _workflow(db_session))
    await _expect_violation(
        db_session,
        "UPDATE execution_steps SET status = 'QUEUED' WHERE id = :id",  # an execution status, not a step one
        {"id": steps[0].id},
        "ck_execution_steps_status",
    )
