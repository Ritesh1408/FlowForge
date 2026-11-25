"""Redis-backed dispatch queue for executions.

A plain Redis list: producers ``LPUSH``, workers will pop from the other end
(``BRPOP``/``BLMOVE``), giving FIFO order. Only basic list commands are used so any
Redis version FlowForge may run against supports them.

Messages carry only the execution ID. PostgreSQL is the source of truth: a worker
loads the execution (definition snapshot, input, status) from the database.
"""

import asyncio
import json
import logging
import uuid

from redis.asyncio import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


class QueueUnavailableError(Exception):
    """The message could not be confirmed as enqueued (Redis error or timeout)."""


def encode_message(execution_id: uuid.UUID) -> str:
    return json.dumps({"execution_id": str(execution_id)})


def decode_message(raw: bytes | str) -> uuid.UUID:
    """Parse a queue message; raises ``ValueError`` if it is malformed."""
    try:
        payload = json.loads(raw)
        return uuid.UUID(payload["execution_id"])
    except (TypeError, KeyError, AttributeError, json.JSONDecodeError) as exc:
        raise ValueError("Malformed execution queue message") from exc


class ExecutionQueue:
    def __init__(self, redis: Redis, key: str, timeout_seconds: float) -> None:
        self._redis = redis
        self._key = key
        self._timeout_seconds = timeout_seconds

    @property
    def key(self) -> str:
        return self._key

    async def enqueue(self, execution_id: uuid.UUID) -> None:
        """Push one execution onto the queue, bounded by the configured timeout.

        On timeout the push may still have reached Redis; callers must treat
        ``QueueUnavailableError`` as "not confirmed", not "definitely absent".
        """
        message = encode_message(execution_id)
        try:
            await asyncio.wait_for(self._redis.lpush(self._key, message), timeout=self._timeout_seconds)
        except TimeoutError as exc:
            logger.error(
                "Enqueue timed out after %.2fs: execution_id=%s", self._timeout_seconds, execution_id
            )
            raise QueueUnavailableError("Timed out pushing to the execution queue") from exc
        except (RedisError, OSError) as exc:
            logger.error(
                "Enqueue failed: execution_id=%s error=%s: %s", execution_id, type(exc).__name__, exc
            )
            raise QueueUnavailableError("Could not push to the execution queue") from exc
