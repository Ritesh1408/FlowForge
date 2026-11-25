"""Allowed status values (AGENTS.md §7). Transition rules are not enforced here."""

from enum import StrEnum


class ExecutionStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    RETRYING = "RETRYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class StepStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    RETRYING = "RETRYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


def status_check_sql(column: str, values: type[StrEnum]) -> str:
    """SQL for a CHECK constraint limiting ``column`` to the enum's values."""
    allowed = ", ".join(f"'{member.value}'" for member in values)
    return f"{column} IN ({allowed})"
