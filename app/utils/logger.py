"""
logger.py — Structured logging configuration for the application.

Provides JSON-formatted log output suitable for ingestion by CloudWatch,
Datadog, or any structured log aggregator. Falls back to human-readable
format when running in DEBUG mode for developer convenience.
"""

import logging
import logging.config
import os
import sys
from pathlib import Path

from app.config import get_settings

settings = get_settings()


class _RequestIdFilter(logging.Filter):
    """Inject a default request_id into log records that lack one."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        return True


def _build_log_config(log_dir: Path, level: str, debug: bool) -> dict:
    """Build a logging.config.dictConfig-compatible configuration dict."""
    is_lambda_env = "AWS_LAMBDA_FUNCTION_NAME" in os.environ
    
    fmt_human = "%(asctime)s | %(levelname)-8s | %(name)-35s | %(message)s"
    fmt_json = (
        '{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s",'
        '"request_id":"%(request_id)s","message":"%(message)s"}'
    )

    formatter = "human" if debug else "json"

    handlers: dict[str, dict] = {
        "console": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": formatter,
            "filters": ["request_id"],
            "level": level,
        }
    }
    root_handlers = ["console"]

    # In AWS Lambda, stdout goes directly to CloudWatch and the filesystem is read-only.
    # Only add file handler if not in Lambda and log directory creation succeeds.
    if not is_lambda_env:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = str(log_dir / "app.log")
            handlers["file"] = {
                "class": "logging.handlers.RotatingFileHandler",
                "filename": log_file,
                "maxBytes": 10 * 1024 * 1024,   # 10 MB
                "backupCount": 5,
                "formatter": formatter,
                "filters": ["request_id"],
                "level": level,
                "encoding": "utf-8",
            }
            root_handlers.append("file")
        except OSError:
            # Fall back safely to console logging if filesystem is read-only
            pass

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "request_id": {"()": _RequestIdFilter},
        },
        "formatters": {
            "human": {"format": fmt_human},
            "json": {"format": fmt_json},
        },
        "handlers": handlers,
        "root": {
            "level": level,
            "handlers": root_handlers,
        },
        "loggers": {
            # Quiet noisy third-party loggers
            "uvicorn": {"level": "INFO", "propagate": True},
            "uvicorn.access": {"level": "WARNING", "propagate": True},
            "botocore": {"level": "WARNING", "propagate": True},
            "boto3": {"level": "WARNING", "propagate": True},
            "sentence_transformers": {"level": "WARNING", "propagate": True},
            "httpx": {"level": "WARNING", "propagate": True},
            "qdrant_client": {"level": "WARNING", "propagate": True},
        },
    }


def setup_logging() -> None:
    """Initialise the logging system from application settings.

    Must be called once, early in the application lifecycle (inside
    the lifespan context manager or at module import time in main.py).
    """
    log_dir = Path(settings.log_dir)
    level = settings.log_level.upper()
    debug = settings.debug

    config = _build_log_config(log_dir, level, debug)
    logging.config.dictConfig(config)

    # One confirmation line so we can verify logging is active
    logging.getLogger(__name__).info(
        "Logging initialised | level=%s | debug=%s | log_file=%s/app.log",
        level,
        debug,
        log_dir,
    )


def get_logger(name: str) -> logging.Logger:
    """Convenience wrapper — returns a named logger.

    Usage::

        from app.utils.logger import get_logger
        logger = get_logger(__name__)
    """
    return logging.getLogger(name)
