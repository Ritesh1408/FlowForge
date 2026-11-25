from fastapi import APIRouter

from flowforge.api.v1 import health, workflows

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(workflows.router)
