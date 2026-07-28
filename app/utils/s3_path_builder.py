"""S3 Path Builder — Reusable helper for constructing and parsing S3 object keys.

Follows the official production S3 structure:
- Account Master: account_master/Account.csv
- Monthly Cost Reports: cost-explorer/{YEAR}/cost_report_{YEAR}-{MONTH}-01.csv
"""

import os
import re
from typing import Optional, Tuple

from app.config import get_settings

settings = get_settings()


def get_account_master_prefix() -> str:
    """Return the configured account master folder prefix (e.g. 'account_master/')."""
    prefix = getattr(settings, "aws_account_master_prefix", "account_master/").strip()
    if not prefix.endswith("/"):
        prefix += "/"
    return prefix


def get_account_master_key() -> str:
    """Return the full S3 object key for Account.csv (e.g. 'account_master/Account.csv')."""
    configured_key = getattr(settings, "aws_account_master_file", "account_master/Account.csv").strip()
    if configured_key:
        return configured_key
    return f"{get_account_master_prefix()}Account.csv"


def get_cost_explorer_prefix(year: Optional[int | str] = None) -> str:
    """Return the cost explorer folder prefix.

    Examples:
        - get_cost_explorer_prefix() -> 'cost-explorer/'
        - get_cost_explorer_prefix(2026) -> 'cost-explorer/2026/'
    """
    base_prefix = getattr(settings, "aws_cost_explorer_prefix", "cost-explorer/").strip()
    if not base_prefix.endswith("/"):
        base_prefix += "/"

    if year:
        year_str = str(year).strip()
        return f"{base_prefix}{year_str}/"
    return base_prefix


def get_monthly_cost_report_key(year: int | str, month: int | str, day: int | str = 1) -> str:
    """Dynamically generate S3 object key for a monthly cost report CSV.

    Examples:
        - get_monthly_cost_report_key(2026, 1) -> 'cost-explorer/2026/cost_report_2026-01-01.csv'
        - get_monthly_cost_report_key("2026", "05") -> 'cost-explorer/2026/cost_report_2026-05-01.csv'
    """
    year_int = int(year)
    month_int = int(month)
    day_int = int(day)

    month_str = f"{month_int:02d}"
    day_str = f"{day_int:02d}"

    filename = f"cost_report_{year_int}-{month_str}-{day_str}.csv"
    prefix = get_cost_explorer_prefix(year_int)
    return f"{prefix}{filename}"


def is_valid_cost_report_key(s3_key: str) -> bool:
    """Check if an S3 key matches the valid cost report CSV filename pattern."""
    if not s3_key or not s3_key.endswith(".csv"):
        return False

    filename = os.path.basename(s3_key)
    return bool(re.match(r"^cost_report_\d{4}-\d{2}-\d{2}\.csv$", filename))


def parse_billing_period_from_key(s3_key: str) -> Optional[Tuple[str, str]]:
    """Extract (billing_period, filename) from an S3 key if valid.

    Example:
        - 'cost-explorer/2026/cost_report_2026-01-01.csv' -> ('2026-01', 'cost_report_2026-01-01.csv')
    """
    if not is_valid_cost_report_key(s3_key):
        return None

    filename = os.path.basename(s3_key)
    match = re.search(r"(\d{4})-(\d{2})", filename)
    if match:
        billing_period = f"{match.group(1)}-{match.group(2)}"
        return (billing_period, filename)
    return None
