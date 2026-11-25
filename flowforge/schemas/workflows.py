"""Request/response schemas for the workflow registry API."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from flowforge.schemas.workflow_definition import MAX_NAME_LENGTH, WorkflowDefinition


class WorkflowCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    description: str | None = Field(default=None, max_length=2000)
    definition: WorkflowDefinition


class WorkflowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    # The stored, already-validated definition (normalized, with defaults filled in).
    definition: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class WorkflowList(BaseModel):
    items: list[WorkflowResponse]
    limit: int
    offset: int
