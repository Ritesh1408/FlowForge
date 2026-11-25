"""Dependency health checks."""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping

logger = logging.getLogger(__name__)

HealthCheck = Callable[[], Awaitable[None]]


class HealthService:
    """Runs named dependency checks concurrently, each bounded by a timeout.

    A check passes if it returns without raising. Failure details are logged
    internally only; callers receive a single healthy/unhealthy result.
    """

    def __init__(self, checks: Mapping[str, HealthCheck], timeout_seconds: float) -> None:
        self._checks = dict(checks)
        self._timeout_seconds = timeout_seconds

    async def is_healthy(self) -> bool:
        results = await asyncio.gather(
            *(self._run_check(name, check) for name, check in self._checks.items())
        )
        return all(results)

    async def _run_check(self, name: str, check: HealthCheck) -> bool:
        try:
            await asyncio.wait_for(check(), timeout=self._timeout_seconds)
        except TimeoutError:
            logger.warning("Health check '%s' timed out after %.2fs", name, self._timeout_seconds)
            return False
        # A health probe must report any dependency failure (driver, network, auth...)
        # as "unhealthy" rather than crash the endpoint; the cause is logged, not hidden.
        except Exception as exc:
            logger.warning("Health check '%s' failed: %s: %s", name, type(exc).__name__, exc)
            return False
        return True
