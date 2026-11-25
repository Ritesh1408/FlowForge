from fastapi import APIRouter, Depends, Request, Response, status

from flowforge.db import session as db
from flowforge.queue import redis_client
from flowforge.schemas.health import HealthResponse
from flowforge.services.health import HealthService

router = APIRouter(tags=["health"])


def get_health_service(request: Request) -> HealthService:
    state = request.app.state
    return HealthService(
        checks={
            "postgresql": lambda: db.ping(state.engine),
            "redis": lambda: redis_client.ping(state.redis),
        },
        timeout_seconds=state.settings.health_check_timeout_seconds,
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": HealthResponse}},
)
async def health(
    response: Response, service: HealthService = Depends(get_health_service)
) -> HealthResponse:
    if await service.is_healthy():
        return HealthResponse(status="ok")
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(status="unavailable")
