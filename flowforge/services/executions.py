"""Execution creation and dispatch.

Order of operations (PostgreSQL is the source of truth, Redis only dispatches):

1. In one transaction: load the workflow, insert the execution (QUEUED, with a copy of
   the definition) and its PENDING steps, plus an ``execution_created`` log entry; commit.
2. Only after the commit succeeds, push the execution ID onto the Redis queue, so a
   worker can never receive an ID whose rows were rolled back.
3. If the push fails, the committed execution is marked FAILED (steps SKIPPED, an
   ``enqueue_failed`` log entry) instead of staying QUEUED with no message.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from flowforge.core.errors import (
    ExecutionPersistenceError,
    ExecutionQueueUnavailableError,
    WorkflowNotFoundError,
)
from flowforge.models import Execution, ExecutionStatus, StepStatus
from flowforge.queue.execution_queue import ExecutionQueue, QueueUnavailableError
from flowforge.repositories import executions as execution_repo
from flowforge.repositories import workflows as workflow_repo

logger = logging.getLogger(__name__)


def _describe(exc: SQLAlchemyError) -> str:
    # Error class names only: SQLAlchemy messages embed SQL parameters, which here
    # include untrusted execution input that must not reach the logs.
    driver_error = getattr(exc, "orig", None)
    return type(exc).__name__ + (f" ({type(driver_error).__name__})" if driver_error is not None else "")


class ExecutionService:
    def __init__(self, session: AsyncSession, queue: ExecutionQueue) -> None:
        self._session = session
        self._queue = queue

    async def create(self, workflow_id: uuid.UUID, input_data: dict[str, Any]) -> Execution:
        """Persist a new QUEUED execution of the workflow and enqueue it.

        Every call creates a new execution; repeated requests are not deduplicated.
        """
        execution = await self._persist(workflow_id, input_data)
        # Plain UUID: a later rollback expires ORM attributes, which cannot lazy-load here.
        execution_id = execution.id
        try:
            await self._queue.enqueue(execution_id)
        except QueueUnavailableError as exc:
            marked = await self._mark_enqueue_failed(execution_id)
            outcome = " and was marked FAILED" if marked else ""
            raise ExecutionQueueUnavailableError(
                f"Execution {execution_id} could not be queued{outcome}. Try again later."
            ) from exc
        logger.info("Execution queued: execution_id=%s workflow_id=%s", execution_id, workflow_id)
        return execution

    async def _persist(self, workflow_id: uuid.UUID, input_data: dict[str, Any]) -> Execution:
        try:
            workflow = await workflow_repo.get_workflow(self._session, workflow_id)
            if workflow is None:
                raise WorkflowNotFoundError(f"Workflow {workflow_id} not found")
            execution, steps = await execution_repo.create_execution(
                self._session, workflow, input_data=input_data
            )
            await execution_repo.add_log(
                self._session,
                execution.id,
                level="INFO",
                event="execution_created",
                message=f"Execution created with {len(steps)} step(s)",
            )
            await self._session.commit()
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.error(
                "Execution could not be persisted: workflow_id=%s error=%s", workflow_id, _describe(exc)
            )
            raise ExecutionPersistenceError(
                "The execution could not be saved and was not queued. Try again later."
            ) from exc
        return execution

    async def _mark_enqueue_failed(self, execution_id: uuid.UUID) -> bool:
        """Record the dispatch failure so the execution does not stay QUEUED forever."""
        try:
            await execution_repo.update_execution_status(
                self._session, execution_id, ExecutionStatus.FAILED, finished_at=datetime.now(UTC)
            )
            await execution_repo.set_pending_steps_status(self._session, execution_id, StepStatus.SKIPPED)
            await execution_repo.add_log(
                self._session,
                execution_id,
                level="ERROR",
                event="enqueue_failed",
                message="Execution could not be added to the queue",
            )
            await self._session.commit()
        except SQLAlchemyError as exc:
            await self._session.rollback()
            # The execution stays QUEUED without a queue message; logged for recovery.
            logger.error(
                "Could not mark execution FAILED after enqueue failure: execution_id=%s error=%s",
                execution_id,
                _describe(exc),
            )
            return False
        logger.warning("Execution marked FAILED after enqueue failure: execution_id=%s", execution_id)
        return True
