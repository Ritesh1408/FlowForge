import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from flowforge.models import Execution, ExecutionStatus, ExecutionStep, StepStatus, Workflow
from flowforge.repositories import executions as execution_repo
from flowforge.repositories import workflows as workflow_repo

pytestmark = pytest.mark.integration


def _definition(*names: str) -> dict:
    return {"steps": [{"name": name, "type": "delay", "config": {"seconds": 1}} for name in names]}


async def _count(session: AsyncSession, model: type, **filters: object) -> int:
    statement = select(func.count()).select_from(model).filter_by(**filters)
    return (await session.execute(statement)).scalar_one()


# --- workflows ---------------------------------------------------------------------


async def test_create_and_get_workflow(db_session: AsyncSession) -> None:
    created = await workflow_repo.create_workflow(
        db_session, name="orders", definition=_definition("a"), description="Order sync"
    )
    db_session.expunge_all()

    loaded = await workflow_repo.get_workflow(db_session, created.id)

    assert loaded is not None and loaded is not created
    assert (loaded.name, loaded.description, loaded.definition) == ("orders", "Order sync", _definition("a"))
    assert isinstance(loaded.id, uuid.UUID)
    assert loaded.created_at is not None and loaded.updated_at is not None


async def test_get_missing_workflow_returns_none(db_session: AsyncSession) -> None:
    assert await workflow_repo.get_workflow(db_session, uuid.uuid4()) is None


async def test_list_workflows_ordered_and_paginated(db_session: AsyncSession) -> None:
    for name in ("w-1", "w-2", "w-3"):
        await workflow_repo.create_workflow(db_session, name=name, definition=_definition("a"))

    listed = await workflow_repo.list_workflows(db_session)
    assert sorted(w.name for w in listed) == ["w-1", "w-2", "w-3"]
    assert [(w.created_at, w.id) for w in listed] == sorted((w.created_at, w.id) for w in listed)

    page = await workflow_repo.list_workflows(db_session, limit=2, offset=1)
    assert [w.id for w in page] == [w.id for w in listed[1:3]]


# --- executions and steps ----------------------------------------------------------


async def test_create_execution_with_steps(db_session: AsyncSession) -> None:
    workflow = await workflow_repo.create_workflow(db_session, name="wf", definition=_definition("s0", "s1", "s2"))

    execution, steps = await execution_repo.create_execution(db_session, workflow, input_data={"order": 7})
    db_session.expunge_all()

    stored = await db_session.get(Execution, execution.id)
    assert stored is not None
    assert stored.workflow_id == workflow.id
    assert stored.status == ExecutionStatus.QUEUED
    assert stored.input == {"order": 7}
    assert stored.definition_snapshot == _definition("s0", "s1", "s2")
    assert stored.created_at is not None and stored.started_at is None and stored.finished_at is None

    rows = (
        await db_session.scalars(
            select(ExecutionStep).where(ExecutionStep.execution_id == execution.id).order_by(ExecutionStep.position)
        )
    ).all()
    assert [(s.position, s.name, s.type, s.status, s.attempt_count) for s in rows] == [
        (0, "s0", "delay", StepStatus.PENDING, 0),
        (1, "s1", "delay", StepStatus.PENDING, 0),
        (2, "s2", "delay", StepStatus.PENDING, 0),
    ]
    assert [s.id for s in rows] == [s.id for s in steps]


async def test_create_execution_defaults_input_to_empty_object(db_session: AsyncSession) -> None:
    workflow = await workflow_repo.create_workflow(db_session, name="wf", definition=_definition("a"))
    execution, _ = await execution_repo.create_execution(db_session, workflow)
    assert execution.input == {}


# Rejecting definitions without usable steps moved to the workflow registry (Phase 3):
# see tests/test_workflow_definition.py::test_malformed_definitions_rejected and the
# registry API tests, which also check that nothing is persisted.


async def test_create_execution_is_all_or_nothing(db_session: AsyncSession) -> None:
    # The third step's name exceeds the column length, so its INSERT fails in the database.
    workflow = await workflow_repo.create_workflow(db_session, name="wf", definition=_definition("ok", "ok2", "x" * 201))

    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await execution_repo.create_execution(db_session, workflow)

    assert await _count(db_session, Execution, workflow_id=workflow.id) == 0
    assert await _count(db_session, ExecutionStep) == 0


async def test_definition_snapshot_unchanged_after_workflow_edit(db_session: AsyncSession) -> None:
    original = _definition("first", "second")
    workflow = await workflow_repo.create_workflow(db_session, name="wf", definition=original)
    execution, _ = await execution_repo.create_execution(db_session, workflow)

    # In-place edit of the workflow's dict must not leak into the snapshot (no shared objects)...
    workflow.definition["steps"][0]["name"] = "mutated-in-memory"
    assert execution.definition_snapshot == _definition("first", "second")
    # ...and neither must a persisted edit of the workflow row.
    workflow.definition = _definition("replacement")
    await db_session.flush()
    db_session.expunge_all()

    reloaded_workflow = await workflow_repo.get_workflow(db_session, workflow.id)
    reloaded_execution = await db_session.get(Execution, execution.id)
    assert reloaded_workflow is not None and reloaded_execution is not None
    assert reloaded_workflow.definition == _definition("replacement")
    assert reloaded_execution.definition_snapshot == _definition("first", "second")


async def test_update_execution_status(db_session: AsyncSession) -> None:
    workflow = await workflow_repo.create_workflow(db_session, name="wf", definition=_definition("a"))
    execution, _ = await execution_repo.create_execution(db_session, workflow)
    started = datetime(2026, 11, 25, 10, 0, tzinfo=UTC)
    finished = datetime(2026, 11, 25, 10, 5, tzinfo=UTC)

    await execution_repo.update_execution_status(db_session, execution.id, ExecutionStatus.RUNNING, started_at=started)
    await execution_repo.update_execution_status(db_session, execution.id, "COMPLETED", finished_at=finished)
    db_session.expunge_all()

    stored = await db_session.get(Execution, execution.id)
    assert stored is not None
    assert (stored.status, stored.started_at, stored.finished_at) == ("COMPLETED", started, finished)


async def test_update_execution_status_rejects_unknown_status_and_id(db_session: AsyncSession) -> None:
    workflow = await workflow_repo.create_workflow(db_session, name="wf", definition=_definition("a"))
    execution, _ = await execution_repo.create_execution(db_session, workflow)

    with pytest.raises(ValueError):
        await execution_repo.update_execution_status(db_session, execution.id, "PENDING")
    with pytest.raises(LookupError):
        await execution_repo.update_execution_status(db_session, uuid.uuid4(), ExecutionStatus.RUNNING)


async def test_update_step_status(db_session: AsyncSession) -> None:
    workflow = await workflow_repo.create_workflow(db_session, name="wf", definition=_definition("a", "b"))
    _, steps = await execution_repo.create_execution(db_session, workflow)
    step_id = steps[0].id
    started = datetime(2026, 11, 25, 10, 0, tzinfo=UTC)
    finished = datetime(2026, 11, 25, 10, 1, tzinfo=UTC)

    await execution_repo.update_step_status(
        db_session, step_id, StepStatus.RETRYING, attempt_count=1, error="timeout", started_at=started
    )
    await execution_repo.update_step_status(
        db_session, step_id, StepStatus.COMPLETED, attempt_count=2, output={"ok": True}, error=None, finished_at=finished
    )
    db_session.expunge_all()

    step = await db_session.get(ExecutionStep, step_id)
    other = await db_session.get(ExecutionStep, steps[1].id)
    assert step is not None and other is not None
    assert (step.status, step.attempt_count, step.output, step.error) == ("COMPLETED", 2, {"ok": True}, None)
    assert (step.started_at, step.finished_at) == (started, finished)  # started_at left unchanged by 2nd call
    assert (other.status, other.attempt_count) == ("PENDING", 0)


async def test_update_step_status_rejects_unknown_status_and_id(db_session: AsyncSession) -> None:
    workflow = await workflow_repo.create_workflow(db_session, name="wf", definition=_definition("a"))
    _, steps = await execution_repo.create_execution(db_session, workflow)

    with pytest.raises(ValueError):
        await execution_repo.update_step_status(db_session, steps[0].id, "QUEUED")
    with pytest.raises(LookupError):
        await execution_repo.update_step_status(db_session, uuid.uuid4(), StepStatus.RUNNING)


# --- logs --------------------------------------------------------------------------


async def test_add_and_list_logs_in_order(db_session: AsyncSession) -> None:
    workflow = await workflow_repo.create_workflow(db_session, name="wf", definition=_definition("a"))
    execution, steps = await execution_repo.create_execution(db_session, workflow)
    other, _ = await execution_repo.create_execution(db_session, workflow)

    await execution_repo.add_log(db_session, execution.id, level="INFO", event="execution.queued", message="queued")
    await execution_repo.add_log(db_session, other.id, level="INFO", event="execution.queued", message="other")
    await execution_repo.add_log(
        db_session,
        execution.id,
        step_id=steps[0].id,
        level="ERROR",
        event="step.failed",
        message="boom",
        data={"attempt": 1},
    )
    await execution_repo.add_log(db_session, execution.id, level="INFO", event="execution.failed", message="done")
    db_session.expunge_all()

    logs = await execution_repo.list_logs(db_session, execution.id)

    assert [(log.event, log.message) for log in logs] == [
        ("execution.queued", "queued"),
        ("step.failed", "boom"),
        ("execution.failed", "done"),
    ]
    assert logs[1].step_id == steps[0].id and logs[1].data == {"attempt": 1} and logs[1].level == "ERROR"
    assert logs[0].step_id is None and logs[0].data is None
    assert [log.created_at for log in logs] == sorted(log.created_at for log in logs)
    assert await execution_repo.list_logs(db_session, uuid.uuid4()) == []
