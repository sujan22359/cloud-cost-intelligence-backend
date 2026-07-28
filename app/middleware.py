"""
middleware.py — Custom FastAPI middleware stack.

Provides:
- RequestLoggingMiddleware  : structured per-request logging with latency
- add_cors_middleware()     : permissive CORS for local development,
                              configurable for production
"""

import logging
import time
import uuid
from collections.abc import Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every HTTP request with method, path, status code, and latency."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = str(uuid.uuid4())[:8]
        start = time.perf_counter()

        # Attach request_id for downstream log correlation
        request.state.request_id = request_id

        logger.info(
            "[%s] → %s %s  client=%s",
            request_id,
            request.method,
            request.url.path,
            request.client.host if request.client else "unknown",
        )

        try:
            response: Response = await call_next(request)
        except Exception as exc:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error(
                "[%s] ✗ %s %s  %.1f ms  UNHANDLED: %s",
                request_id, request.method, request.url.path, elapsed, exc,
            )
            raise

        elapsed = (time.perf_counter() - start) * 1000
        level = logging.WARNING if response.status_code >= 400 else logging.INFO
        logger.log(
            level,
            "[%s] ← %s %s  %d  %.1f ms",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            elapsed,
        )

        # Expose request ID to the client for support tracing
        response.headers["X-Request-ID"] = request_id
        return response


def add_cors_middleware(app: FastAPI, allow_origins: list[str] | None = None) -> None:
    """Attach CORS middleware to *app*.

    Args:
        app: The FastAPI application instance.
        allow_origins: List of allowed origins. Defaults to wildcard (dev-friendly).
                       In production, pass a restricted list of origins.
    """
    origins = allow_origins or ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
