"""FastAPI application factory.

Run with: uvicorn flowforge.main:create_app --factory
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from flowforge.api.errors import register_exception_handlers
from flowforge.api.v1.router import api_router
from flowforge.core.config import Settings, get_settings
from flowforge.core.logging import configure_logging
from flowforge.db.session import create_engine, create_session_factory
from flowforge.queue.redis_client import create_redis_client

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    # Clients connect lazily, so startup succeeds even if PostgreSQL/Redis are down;
    # the health endpoint reports their availability.
    engine = create_engine(settings.database_url.get_secret_value())
    redis = create_redis_client(settings.redis_url.get_secret_value())
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    app.state.redis = redis
    logger.info("FlowForge started (env=%s)", settings.app_env)
    try:
        yield
    finally:
        await redis.aclose()
        await engine.dispose()
        logger.info("FlowForge shut down; connections closed")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    app = FastAPI(title="FlowForge", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    register_exception_handlers(app)
    app.include_router(api_router, prefix="/api/v1")
    return app
