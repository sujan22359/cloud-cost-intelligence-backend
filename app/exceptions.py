"""
exceptions.py — Application-wide exception handlers for FastAPI.

Converts common exception types into structured JSON error responses so
the API always returns consistent error payloads regardless of where an
error originates.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

logger = logging.getLogger(__name__)


# ── Custom exception types ────────────────────────────────────────────────────

class AWSServiceError(Exception):
    """Raised when an AWS API call fails (Cost Explorer, S3, Bedrock, etc.)."""

    def __init__(self, service: str, detail: str) -> None:
        self.service = service
        self.detail = detail
        super().__init__(f"[{service}] {detail}")


class DocumentNotFoundError(Exception):
    """Raised when a requested document/file cannot be located."""

    def __init__(self, resource: str) -> None:
        self.resource = resource
        super().__init__(f"Resource not found: {resource}")


class IndexingError(Exception):
    """Raised when document indexing fails."""


class KnowledgeNotFoundError(Exception):
    """Raised when a requested knowledge base entry is not found."""

    def __init__(self, knowledge_id: int) -> None:
        self.knowledge_id = knowledge_id
        super().__init__(f"Knowledge record not found for id: {knowledge_id}")


class KnowledgeValidationError(Exception):
    """Raised when knowledge base entry input validation fails."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


# ── Error response builder ────────────────────────────────────────────────────

def _error_response(
    status_code: int,
    error: str,
    detail: str | list[Any],
    request_id: str | None = None,
) -> JSONResponse:
    content: dict[str, Any] = {"error": error, "detail": detail}
    if request_id:
        content["request_id"] = request_id
    return JSONResponse(status_code=status_code, content=content)


# ── Handler registration ──────────────────────────────────────────────────────

def register_exception_handlers(app: FastAPI) -> None:
    """Attach all global exception handlers to the FastAPI *app*."""

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logger.warning("Validation error on %s: %s", request.url.path, exc.errors())
        return _error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            error="Validation Error",
            detail=exc.errors(),
            request_id=request_id,
        )

    @app.exception_handler(AWSServiceError)
    async def aws_service_error_handler(
        request: Request, exc: AWSServiceError
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logger.error("AWSServiceError [%s]: %s", exc.service, exc.detail)
        return _error_response(
            status_code=status.HTTP_502_BAD_GATEWAY,
            error=f"AWS {exc.service} Error",
            detail=exc.detail,
            request_id=request_id,
        )

    @app.exception_handler(DocumentNotFoundError)
    async def document_not_found_handler(
        request: Request, exc: DocumentNotFoundError
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        return _error_response(
            status_code=status.HTTP_404_NOT_FOUND,
            error="Not Found",
            detail=str(exc),
            request_id=request_id,
        )

    @app.exception_handler(KnowledgeNotFoundError)
    async def knowledge_not_found_handler(
        request: Request, exc: KnowledgeNotFoundError
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        return _error_response(
            status_code=status.HTTP_404_NOT_FOUND,
            error="Knowledge Not Found",
            detail=str(exc),
            request_id=request_id,
        )

    @app.exception_handler(KnowledgeValidationError)
    async def knowledge_validation_error_handler(
        request: Request, exc: KnowledgeValidationError
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logger.warning("KnowledgeValidationError on %s: %s", request.url.path, exc.detail)
        return _error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            error="Knowledge Validation Error",
            detail=exc.detail,
            request_id=request_id,
        )

    @app.exception_handler(IndexingError)
    async def indexing_error_handler(
        request: Request, exc: IndexingError
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logger.error("IndexingError: %s", exc)
        return _error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error="Indexing Error",
            detail=str(exc),
            request_id=request_id,
        )

    @app.exception_handler(FileNotFoundError)
    async def file_not_found_handler(
        request: Request, exc: FileNotFoundError
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        return _error_response(
            status_code=status.HTTP_404_NOT_FOUND,
            error="File Not Found",
            detail=str(exc),
            request_id=request_id,
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(
        request: Request, exc: ValueError
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logger.warning("ValueError on %s: %s", request.url.path, exc)
        return _error_response(
            status_code=status.HTTP_400_BAD_REQUEST,
            error="Bad Request",
            detail=str(exc),
            request_id=request_id,
        )

    @app.exception_handler(Exception)
    async def generic_error_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        logger.exception("Unhandled exception on %s", request.url.path)
        return _error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error="Internal Server Error",
            detail="An unexpected error occurred. Check server logs for details.",
            request_id=request_id,
        )
