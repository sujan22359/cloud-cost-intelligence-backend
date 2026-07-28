import csv
import io
import logging
import os
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import get_settings
from app.constants import ROOT_ACCOUNT_ID
from app.db.cost_models import MonthlyCost, ServiceCost
from app.etl.normalization import normalize_service_name
from app.etl.validator import ETLValidator
from app.utils.aws_utils import get_s3_client
from app.utils.s3_path_builder import (
    get_cost_explorer_prefix,
    is_valid_cost_report_key,
    parse_billing_period_from_key,
)

logger = logging.getLogger(__name__)
settings = get_settings()


def get_billing_csv_files() -> List[Tuple[str, str]]:
    """Discover all CSV files in S3 under cost-explorer/ and sort them by billing month."""
    logger.info("Discovering billing CSVs in S3 using s3_path_builder...")
    s3_client = get_s3_client()
    s3_bucket = settings.aws_s3_bucket
    s3_prefix = get_cost_explorer_prefix()

    try:
        response = s3_client.list_objects_v2(Bucket=s3_bucket, Prefix=s3_prefix)
    except Exception as e:
        logger.error(f"Failed to list S3 objects under prefix '{s3_prefix}': {e}")
        return []

    if "Contents" not in response:
        logger.warning(f"No billing CSV files found in S3 bucket '{s3_bucket}' under prefix '{s3_prefix}'.")
        return []

    files = []
    for obj in response["Contents"]:
        key = obj["Key"]
        parsed = parse_billing_period_from_key(key)
        if not parsed:
            if key.endswith(".csv"):
                logger.warning(f"Skipped invalid cost report key format: {key}")
            continue

        month, _ = parsed
        files.append((month, key))

    # Sort files by billing month
    files.sort(key=lambda x: x[0])
    return files


def filter_and_log_months(files: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    """Determine the latest month. If it is the current calendar month, skip it."""
    if not files:
        return []

    latest_month = files[-1][0]
    current_calendar_month = datetime.utcnow().strftime("%Y-%m")

    if latest_month == current_calendar_month:
        logger.info(f"Month skipped: latest month {latest_month} matches current calendar month.")
        return [f for f in files if f[0] != latest_month]

    return files


def process_billing_csv(
    session: Session,
    s3_key: str,
    billing_period: str,
    accounts_map: Dict[str, Dict[str, Any]]
) -> Dict[str, Any]:
    """Process a single billing CSV, validate columns, merge accounts, and save to DB."""
    filename = os.path.basename(s3_key)
    logger.info(f"Reading billing CSV from S3: {s3_key}")
    s3_client = get_s3_client()
    s3_bucket = settings.aws_s3_bucket

    # Validate filename format using s3_path_builder helper
    if not is_valid_cost_report_key(s3_key):
        logger.error(f"Filename validation failed for S3 key '{s3_key}'. Rejecting file.")
        return {
            "status": "failed",
            "reason": "Invalid filename format",
            "rows_read": 0,
            "rows_imported": 0,
            "rows_updated": 0,
            "duplicates": 0,
            "root_skipped": 0,
            "unknown_accounts": 0,
        }

    try:
        response = s3_client.get_object(Bucket=s3_bucket, Key=s3_key)
        csv_content = response["Body"].read().decode("utf-8")
    except Exception as e:
        logger.error(f"Failed to fetch billing CSV {s3_key}: {e}")
        return {
            "status": "failed",
            "reason": f"Fetch failed: {e}",
            "rows_read": 0,
            "rows_imported": 0,
            "rows_updated": 0,
            "duplicates": 0,
            "root_skipped": 0,
            "unknown_accounts": 0,
        }

    # Validate CSV structure before import
    try:
        reader_check = csv.reader(io.StringIO(csv_content))
        header = next(reader_check)
    except StopIteration:
        logger.error(f"CSV validation failed for {filename}: File is empty")
        return {
            "status": "failed",
            "reason": "CSV file is empty",
            "rows_read": 0,
            "rows_imported": 0,
            "rows_updated": 0,
            "duplicates": 0,
            "root_skipped": 0,
            "unknown_accounts": 0,
        }
    except Exception as e:
        logger.error(f"CSV validation failed for {filename}: {e}")
        return {
            "status": "failed",
            "reason": f"CSV structure check failed: {e}",
            "rows_read": 0,
            "rows_imported": 0,
            "rows_updated": 0,
            "duplicates": 0,
            "root_skipped": 0,
            "unknown_accounts": 0,
        }

    required_cols = {"Month", "Account ID", "Service", "Region", "Cost", "Currency"}
    missing_cols = required_cols - set(header)
    if missing_cols:
        logger.error(f"CSV validation failed for {filename}: Missing columns {missing_cols}")
        return {
            "status": "failed",
            "reason": f"Missing required columns {missing_cols}",
            "rows_read": 0,
            "rows_imported": 0,
            "rows_updated": 0,
            "duplicates": 0,
            "root_skipped": 0,
            "unknown_accounts": 0,
        }

    reader = csv.DictReader(io.StringIO(csv_content))
    validator = ETLValidator(set(accounts_map.keys()))

    rows_read = 0
    rows_loaded = 0
    rows_skipped = 0
    root_skipped = 0

    service_cost_objects = []

    for row_idx, row in enumerate(reader, start=2):  # Header was row 1
        rows_read += 1
        account_id = row.get("Account ID", "").strip()

        # Skip Root account before validation
        if account_id == ROOT_ACCOUNT_ID:
            root_skipped += 1
            continue

        if not validator.validate_billing_row(row, row_idx, billing_period):
            rows_skipped += 1
            continue

        raw_service_name = row["Service"].strip()
        region = row["Region"].strip()
        cost = Decimal(row["Cost"].strip())
        currency = row["Currency"].strip()

        # Normalize service
        business_service_name = normalize_service_name(raw_service_name)

        # Merge account details
        account = accounts_map.get(account_id) or {}
        account_name = account.get("account_name")
        product = account.get("product")
        team = account.get("team")
        environment = account.get("environment")
        developer_type = account.get("developer_type")

        # Do NOT set obsolete service_name directly; write raw_service_name and business_service_name
        service_cost_objects.append(ServiceCost(
            billing_period=billing_period,
            account_id=account_id,
            account_name=account_name,
            product=product,
            team=team,
            environment=environment,
            developer_type=developer_type,
            raw_service_name=raw_service_name,
            business_service_name=business_service_name,
            region=region,
            cost=cost,
            currency=currency,
            created_at=datetime.utcnow()
        ))
        rows_loaded += 1

    # Bulk insert for better performance and transaction rollback
    try:
        # Delete existing rows for this billing period to allow clean re-runs
        session.query(ServiceCost).filter(ServiceCost.billing_period == billing_period).delete()
        
        session.bulk_save_objects(service_cost_objects)
        session.commit()
    except Exception as e:
        session.rollback()
        logger.exception(f"Bulk insert failed for billing period {billing_period}. Rolling back transaction.")
        return {
            "status": "failed",
            "reason": f"Database bulk insert error: {e}",
            "rows_read": rows_read,
            "rows_imported": 0,
            "rows_updated": 0,
            "duplicates": validator.duplicates_count,
            "root_skipped": root_skipped,
            "unknown_accounts": validator.unknown_accounts_count,
        }

    # Rebuild monthly cost summary only after successful service_costs import
    try:
        rebuild_monthly_cost(session, billing_period)
    except Exception as e:
        session.rollback()
        logger.exception(f"Monthly summary rebuild failed for billing period {billing_period}. Rolling back.")
        return {
            "status": "failed",
            "reason": f"Database rebuild error: {e}",
            "rows_read": rows_read,
            "rows_imported": rows_loaded,
            "rows_updated": 0,
            "duplicates": validator.duplicates_count,
            "root_skipped": root_skipped,
            "unknown_accounts": validator.unknown_accounts_count,
        }

    # Print requested single summary of Root Records Skipped
    logger.info(f"Root Records Skipped: {root_skipped}")

    return {
        "status": "success",
        "rows_read": rows_read,
        "rows_imported": rows_loaded,
        "rows_updated": 0,
        "duplicates": validator.duplicates_count,
        "root_skipped": root_skipped,
        "unknown_accounts": validator.unknown_accounts_count,
    }


def rebuild_monthly_cost(session: Session, billing_period: str) -> None:
    """Rebuild monthly_costs table from imported service_costs."""
    total_cost = (
        session.query(func.sum(ServiceCost.cost))
        .filter(ServiceCost.billing_period == billing_period)
        .scalar()
    ) or Decimal("0.00")

    # Determine start_date and end_date
    year, month = map(int, billing_period.split("-"))
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month + 1, 1)

    existing = session.query(MonthlyCost).filter(MonthlyCost.billing_period == billing_period).first()
    if existing:
        existing.total_cost = total_cost
        existing.start_date = start_date
        existing.end_date = end_date
        existing.currency = "USD"
    else:
        session.add(MonthlyCost(
            billing_period=billing_period,
            start_date=start_date,
            end_date=end_date,
            total_cost=total_cost,
            currency="USD"
        ))
    session.commit()
    logger.info(f"Rebuild monthly costs: period={billing_period}, total_cost={total_cost}")
