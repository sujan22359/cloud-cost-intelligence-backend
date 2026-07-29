"""FastAPI entry point for the AWS Cost Intelligence Assistant."""

from contextlib import asynccontextmanager
import logging
from typing import AsyncIterator

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from mangum import Mangum
from sqlalchemy import text

from app.api.auth_routes import router as auth_router
from app.api.cost_routes import router as cost_router
from app.api.database_routes import router as database_router
from app.api.health_routes import router as health_router
from app.api.knowledge_routes import router as knowledge_router
from app.api.qa_routes import router as qa_router
from app.config import get_settings
from app.core.security import get_current_user
from app.db import models  # noqa: F401
from app.db.database import Base, engine
from app.exceptions import register_exception_handlers
from app.middleware import RequestLoggingMiddleware, add_cors_middleware
from app.utils.logger import setup_logging

setup_logging()

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Lightweight startup lifecycle optimized for AWS Lambda cold-starts and local dev."""
    logger.info("Application Started")
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database Connected")
    except Exception as exc:
        logger.warning("Database connection check warning: %s — continuing API startup", exc)

    logger.info("Lambda Runtime Ready")

    try:
        from app.services.cost_query_service import CostQueryService
        from app.services.entity_resolver import validate_startup_service_aliases
        svc = CostQueryService()
        avail = svc.get_available_service_names()
        if avail:
            validate_startup_service_aliases(avail)
    except Exception as exc:
        logger.warning("Startup service alias validation skipped: %s", exc)

    yield

    logger.info("Shutting down %s", settings.app_name)


def create_app() -> FastAPI:
    """Create the FastAPI application."""
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "AI-powered AWS Cost Intelligence Assistant. "
            "Analyses synchronized AWS Cost Explorer data stored in PostgreSQL using Amazon Bedrock Claude 3 Haiku."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    add_cors_middleware(app)
    app.add_middleware(RequestLoggingMiddleware)
    register_exception_handlers(app)

    # Public Routes
    app.include_router(health_router)
    app.include_router(auth_router)

    # Protected Business Routes (Require valid JWT Bearer Token)
    protected_deps = [Depends(get_current_user)]
    app.include_router(cost_router, dependencies=protected_deps)
    app.include_router(qa_router, dependencies=protected_deps)
    app.include_router(database_router, dependencies=protected_deps)
    app.include_router(knowledge_router, dependencies=protected_deps)

    @app.get("/", include_in_schema=False)
    async def root() -> JSONResponse:
        return JSONResponse({
            "service": settings.app_name,
            "version": settings.app_version,
            "health": "/health",
            "docs": "/docs",
            "endpoints": {
                "ask": "POST /ask",
                "monthly_cost": "GET /monthly-cost",
                "service_breakdown": "GET /service-breakdown",
            },
        })

    return app


app = create_app()
handler = Mangum(app)
