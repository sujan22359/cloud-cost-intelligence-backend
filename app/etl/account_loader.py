import csv
import io
import logging
from datetime import datetime
from typing import Any, Dict

from sqlalchemy.orm import Session

from app.config import get_settings
from app.constants import (
    ROOT_ACCOUNT_ID,
    ROOT_ENV_NAME,
    ROOT_TEAM_NAME,
    VALID_PRODUCTS,
)
from app.db.cost_models import AccountMaster
from app.utils.aws_utils import get_s3_client
from app.utils.s3_path_builder import get_account_master_key

logger = logging.getLogger(__name__)
settings = get_settings()


def load_accounts(session: Session) -> Dict[str, Dict[str, Any]]:
    """Download Account.csv from S3 using s3_path_builder, parse columns, and upsert to database."""
    logger.info("Reading Account.csv from S3...")
    s3_client = get_s3_client()
    s3_bucket = settings.aws_s3_bucket
    s3_key = get_account_master_key()

    try:
        response = s3_client.get_object(Bucket=s3_bucket, Key=s3_key)
        csv_content = response["Body"].read().decode("utf-8")
    except Exception as e:
        logger.error(f"Failed to fetch Account.csv from S3 using key '{s3_key}': {e}")
        raise

    reader = csv.DictReader(io.StringIO(csv_content))
    accounts_map = {}
    rows_loaded = 0
    root_ignored = 0

    for row in reader:
        account_id = (row.get("Account ID") or "").strip()
        account_name = (row.get("Name") or "").strip()
        product = (row.get("Product") or "").strip()
        team = (row.get("Team") or "").strip()
        environment = (row.get("Environment") or "").strip()
        developer_type = (row.get("Developer Type") or "").strip()

        # Enforce Root ignoring rule
        if team == ROOT_TEAM_NAME or environment == ROOT_ENV_NAME or account_id == ROOT_ACCOUNT_ID:
            root_ignored += 1
            logger.info(f"Root ignored: {account_name} ({account_id})")
            continue

        # Enforce valid products check
        if product not in VALID_PRODUCTS:
            product = None

        # Sanitize empty strings to None
        if not team:
            team = None
        if not environment:
            environment = None
        if not developer_type:
            developer_type = None

        # Upsert logic to DB
        existing = session.query(AccountMaster).filter(AccountMaster.account_id == account_id).first()
        if existing:
            existing.account_name = account_name
            existing.product = product
            existing.team = team
            existing.environment = environment
            existing.developer_type = developer_type
            existing.updated_at = datetime.utcnow()
        else:
            session.add(AccountMaster(
                account_id=account_id,
                account_name=account_name,
                product=product,
                team=team,
                environment=environment,
                developer_type=developer_type,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow()
            ))

        accounts_map[account_id] = {
            "account_id": account_id,
            "account_name": account_name,
            "product": product,
            "team": team,
            "environment": environment,
            "developer_type": developer_type
        }
        rows_loaded += 1

    session.commit()

    # Synchronize updated account master fields into service_costs
    try:
        from sqlalchemy import text
        session.execute(
            text("""
                UPDATE service_costs sc
                SET 
                    developer_type = am.developer_type,
                    account_name = am.account_name,
                    product = am.product,
                    team = am.team,
                    environment = am.environment
                FROM account_master am
                WHERE sc.account_id = am.account_id
            """)
        )
        session.commit()
        logger.info("Synchronized account master metadata to service_costs table.")
    except Exception as sync_err:
        logger.warning(f"Metadata sync to service_costs encountered non-fatal error: {sync_err}")

    logger.info(f"Account.csv read complete: {rows_loaded} rows loaded, {root_ignored} root accounts ignored.")
    return accounts_map
