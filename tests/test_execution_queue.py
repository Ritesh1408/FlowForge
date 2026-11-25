"""Unit tests for the Redis execution queue (fake Redis client, no live services)."""

import asyncio
import json
import uuid

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import ResponseError

from flowforge.core.config import Settings
from flowforge.queue.execution_queue import (
    ExecutionQueue,
    QueueUnavailableError,
    decode_message,
    encode_message,
)


class FakeRedis:
    def __init__(self, *, fail_with: Exception | None = None, delay: float = 0.0) -> None:
        self.pushed: list[tuple[str, str]] = []
        self.fail_with = fail_with
        self.delay = delay

    async def lpush(self, key: str, value: str) -> int:
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail_with:
            raise self.fail_with
        self.pushed.append((key, value))
        return len(self.pushed)


def test_message_contains_only_the_execution_id() -> None:
    execution_id = uuid.uuid4()

    message = encode_message(execution_id)

    assert json.loads(message) == {"execution_id": str(execution_id)}
    assert decode_message(message) == execution_id
    assert decode_message(message.encode()) == execution_id


@pytest.mark.parametrize(
    "raw",
    ["not json", "[]", "{}", '{"execution_id": 5}', '{"execution_id": "nope"}', "null"],
)
def test_decode_rejects_malformed_messages(raw: str) -> None:
    with pytest.raises(ValueError):
        decode_message(raw)


async def test_enqueue_pushes_message_to_configured_key() -> None:
    redis = FakeRedis()
    queue = ExecutionQueue(redis, "ff:queue", timeout_seconds=1)  # type: ignore[arg-type]
    execution_id = uuid.uuid4()

    await queue.enqueue(execution_id)

    assert redis.pushed == [("ff:queue", encode_message(execution_id))]


@pytest.mark.parametrize(
    "error",
    [RedisConnectionError("Connection refused"), ResponseError("WRONGTYPE"), OSError("network down")],
    ids=["connection", "response", "os"],
)
async def test_enqueue_redis_failure_raises_queue_unavailable(error: Exception) -> None:
    queue = ExecutionQueue(FakeRedis(fail_with=error), "ff:queue", timeout_seconds=1)  # type: ignore[arg-type]

    with pytest.raises(QueueUnavailableError) as raised:
        await queue.enqueue(uuid.uuid4())

    assert raised.value.__cause__ is error


async def test_enqueue_is_bounded_by_timeout() -> None:
    redis = FakeRedis(delay=5)
    queue = ExecutionQueue(redis, "ff:queue", timeout_seconds=0.05)  # type: ignore[arg-type]

    with pytest.raises(QueueUnavailableError):
        await asyncio.wait_for(queue.enqueue(uuid.uuid4()), timeout=2)

    assert redis.pushed == []


def test_queue_settings_defaults_and_validation(unit_settings: Settings) -> None:
    assert unit_settings.execution_queue_key == "flowforge:queue:executions"
    assert unit_settings.queue_enqueue_timeout_seconds == 2.0
    with pytest.raises(ValueError):
        unit_settings.model_validate({**unit_settings.model_dump(), "queue_enqueue_timeout_seconds": 0})
    with pytest.raises(ValueError):
        unit_settings.model_validate({**unit_settings.model_dump(), "execution_queue_key": ""})
