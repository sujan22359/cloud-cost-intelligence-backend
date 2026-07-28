"""
helpers.py — Shared utility functions used across the application.
"""

import logging
import os
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


# ── Date Utilities ────────────────────────────────────────────────────────────

def get_last_month_range() -> tuple[str, str]:
    """Return (start, end) ISO date strings for the previous calendar month."""
    today = date.today()
    first_of_this_month = today.replace(day=1)
    last_of_last_month = first_of_this_month - timedelta(days=1)
    first_of_last_month = last_of_last_month.replace(day=1)
    return first_of_last_month.isoformat(), first_of_this_month.isoformat()


def get_current_month_range() -> tuple[str, str]:
    """Return (start, end) ISO date strings for the current calendar month."""
    today = date.today()
    start = today.replace(day=1).isoformat()
    # Cost Explorer end date is exclusive, so use tomorrow for 'today'
    end = (today + timedelta(days=1)).isoformat()
    return start, end


def get_date_range_months(months: int = 6) -> tuple[str, str]:
    """Return (start, end) covering the last *months* calendar months."""
    today = date.today()
    start = (today - timedelta(days=30 * months)).replace(day=1)
    return start.isoformat(), today.isoformat()


def format_month_label(date_str: str) -> str:
    """Convert 'YYYY-MM-DD' → 'YYYY-MM' for grouping / display."""
    return date_str[:7]


# ── File Utilities ────────────────────────────────────────────────────────────

def ensure_dir(path: str | Path) -> Path:
    """Create directory (and parents) if it does not exist; return the Path."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def generate_unique_filename(original_name: str) -> str:
    """Prepend a UUID4 to the original filename to avoid S3 collisions."""
    stem = Path(original_name).stem
    suffix = Path(original_name).suffix
    return f"{uuid.uuid4().hex}_{stem}{suffix}"


def get_upload_path(filename: str) -> Path:
    """Return absolute path for a file in the configured upload directory."""
    upload_dir = ensure_dir(settings.upload_dir)
    return upload_dir / filename


# ── Logging Utilities ─────────────────────────────────────────────────────────

def setup_logging() -> None:
    """Configure root logger with JSON-friendly structured output."""
    ensure_dir(settings.log_dir)
    log_file = Path(settings.log_dir) / "app.log"

    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    handlers: list[logging.Handler] = [
        logging.StreamHandler(),
        logging.FileHandler(log_file),
    ]

    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    logging.basicConfig(level=level, format=fmt, handlers=handlers)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


# ── Cost Formatting ───────────────────────────────────────────────────────────

def safe_float(value: str | float | None, default: float = 0.0) -> float:
    """Safely convert an arbitrary value to float."""
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def format_cost(amount: float, currency: str = "USD") -> str:
    """Format a cost amount for display, e.g. '$1,234.56 USD'."""
    return f"${amount:,.2f} {currency}"


def calculate_percentage(part: float, total: float) -> float:
    """Return the percentage of *part* relative to *total*, or 0.0 if total is 0."""
    if total == 0:
        return 0.0
    return round((part / total) * 100, 2)
