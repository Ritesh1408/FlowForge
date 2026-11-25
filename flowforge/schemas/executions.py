"""Request/response schemas for execution creation."""

import json
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_INPUT_BYTES = 64 * 1024  # size of the compact JSON encoding
MAX_INPUT_DEPTH = 10  # the input object itself is depth 1


def _check_structure(value: Any, levels_left: int) -> None:
    """Reject nesting deeper than allowed (stops at the limit, so recursion stays shallow)
    and NUL characters, which PostgreSQL text/JSONB cannot store."""
    if isinstance(value, str):
        if "\x00" in value:
            raise ValueError("Input strings must not contain NUL characters")
        return
    if not isinstance(value, dict | list):
        return
    if levels_left == 0:
        raise ValueError(f"Input nesting must not exceed {MAX_INPUT_DEPTH} levels")
    if isinstance(value, dict):
        for key, child in value.items():
            _check_structure(key, levels_left)
            _check_structure(child, levels_left - 1)
    else:
        for child in value:
            _check_structure(child, levels_left - 1)


class ExecutionCreate(BaseModel):
    """Body of ``POST /workflows/{id}/execute``. Input is untrusted data: it is only
    bounded and stored, never interpreted or executed."""

    model_config = ConfigDict(extra="forbid")

    input: dict[str, Any] = Field(default_factory=dict)

    @field_validator("input")
    @classmethod
    def _bounded_json(cls, value: dict[str, Any]) -> dict[str, Any]:
        _check_structure(value, MAX_INPUT_DEPTH)
        try:
            # allow_nan=False: NaN/Infinity are not valid JSON and PostgreSQL JSONB rejects them.
            encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        except ValueError as exc:
            raise ValueError("Input must not contain NaN or Infinity") from exc
        if len(encoded.encode("utf-8")) > MAX_INPUT_BYTES:
            raise ValueError(f"Input must not exceed {MAX_INPUT_BYTES} bytes as JSON")
        return value


class ExecutionCreated(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workflow_id: uuid.UUID
    status: str
    created_at: datetime
