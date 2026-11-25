import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from flowforge.models.base import Base
from flowforge.models.status import ExecutionStatus, StepStatus, status_check_sql


class Execution(Base):
    __tablename__ = "executions"
    __table_args__ = (CheckConstraint(status_check_sql("status", ExecutionStatus), name="status"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    workflow_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workflows.id", ondelete="RESTRICT"))
    # Copy of the workflow definition taken at creation; later workflow edits do not affect it.
    definition_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text, server_default=ExecutionStatus.QUEUED.value)
    input: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExecutionStep(Base):
    __tablename__ = "execution_steps"
    __table_args__ = (
        # Also serves GET /executions/{id}/steps (filter by execution, order by position).
        UniqueConstraint("execution_id", "position"),
        CheckConstraint(status_check_sql("status", StepStatus), name="status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    execution_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("executions.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(Text, server_default=StepStatus.PENDING.value)
    attempt_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ExecutionLog(Base):
    __tablename__ = "execution_logs"
    # Serves GET /executions/{id}/logs (filter by execution, order by time).
    __table_args__ = (Index(None, "execution_id", "created_at"),)

    # Monotonic surrogate key; also breaks ties between entries with equal timestamps.
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    execution_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("executions.id", ondelete="CASCADE"))
    step_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("execution_steps.id", ondelete="CASCADE")
    )
    level: Mapped[str] = mapped_column(String(20))
    event: Mapped[str] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # clock_timestamp(), not now(): entries written in one transaction keep distinct times.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
