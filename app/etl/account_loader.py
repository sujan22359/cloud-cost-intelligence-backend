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

    csv_content = None

    # 1. Try exact primary key
    try:
        response = s3_client.get_object(Bucket=s3_bucket, Key=s3_key)
        csv_content = response["Body"].read().decode("utf-8")
    except Exception as e:
        logger.warning(f"Primary key '{s3_key}' not found in S3 ({e}). Searching alternative account master keys...")

    # 2. Try alternative common keys
    if csv_content is None:
        candidate_keys = [
            "account_master/account.csv",
            "account_master/Account_Master.csv",
            "account_master/Account_master.csv",
            "account_master/Account.CSV",
            "Account.csv",
            "account.csv",
        ]
        for key in candidate_keys:
            try:
                response = s3_client.get_object(Bucket=s3_bucket, Key=key)
                csv_content = response["Body"].read().decode("utf-8")
                logger.info(f"Successfully loaded account master from fallback key '{key}'")
                break
            except Exception:
                continue

    # 3. If still not found, list objects under prefix account_master/
    if csv_content is None:
        try:
            list_res = s3_client.list_objects_v2(Bucket=s3_bucket, Prefix="account_master/")
            for obj in list_res.get("Contents", []):
                obj_key = obj.get("Key", "")
                if obj_key.lower().endswith(".csv"):
                    response = s3_client.get_object(Bucket=s3_bucket, Key=obj_key)
                    csv_content = response["Body"].read().decode("utf-8")
                    logger.info(f"Found account master file via S3 listing: '{obj_key}'")
                    break
        except Exception as err:
            logger.warning(f"Failed to list account_master/ prefix in S3: {err}")

    # 4. Graceful Fallback if Account.csv is completely absent
    if csv_content is None:
        logger.warning("Account.csv not found in S3 bucket '%s'. Fallback: loading existing accounts from database.", s3_bucket)
        existing_db_accounts = session.query(AccountMaster).all()
        accounts_map = {}
        for am in existing_db_accounts:
            if am.account_id:
                accounts_map[am.account_id] = {
                    "account_id": am.account_id,
                    "account_name": am.account_name,
                    "product": am.product,
                    "team": am.team,
                    "environment": am.environment,
                    "developer_type": am.developer_type
                }
        return accounts_map

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
