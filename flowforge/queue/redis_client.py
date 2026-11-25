"""Async Redis client creation and connectivity check."""

from redis.asyncio import Redis
from redis.exceptions import RedisError


def create_redis_client(redis_url: str) -> Redis:
    """Create the async client. No connection is opened until first command."""
    return Redis.from_url(redis_url)


async def ping(client: Redis) -> None:
    """Send PING; raises if Redis is unreachable or answers unexpectedly."""
    if not await client.ping():
        raise RedisError("Unexpected PING response")
