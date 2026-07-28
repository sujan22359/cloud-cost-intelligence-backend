import logging
import re
from decimal import Decimal
from typing import Dict, Set

logger = logging.getLogger(__name__)


class ETLValidator:
    """Validator for billing records, logging warnings and skipping invalid records."""

    def __init__(self, known_account_ids: Set[str]) -> None:
        self.known_account_ids = known_account_ids
        self.warned_unknown_accounts: Set[str] = set()
        self.seen_keys: Set[tuple] = set()
        self.unknown_accounts_count = 0
        self.duplicates_count = 0

    def validate_billing_row(self, row: Dict[str, str], row_num: int, billing_period: str) -> bool:
        """Validate a single billing CSV row. Returns True if valid, False to skip."""
        # 1. Required columns
        required_cols = {"Month", "Account ID", "Service", "Region", "Cost", "Currency"}
        missing_cols = required_cols - set(row.keys())
        if missing_cols:
            logger.warning(f"Row {row_num}: Missing required columns: {missing_cols}")
            return False

        month = row.get("Month", "").strip()
        account_id = row.get("Account ID", "").strip()
        service = row.get("Service", "").strip()
        region = row.get("Region", "").strip()
        cost_str = row.get("Cost", "").strip()
        currency = row.get("Currency", "").strip()

        # 2. Month format validation (YYYY-MM-DD)
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", month):
            logger.warning(f"Row {row_num}: Invalid Month format '{month}'")
            return False

        # 3. Missing Account ID
        if not account_id:
            logger.warning(f"Row {row_num}: Missing Account ID")
            return False

        # 4. Unknown Account ID (Log once per unknown account ID, skip record)
        if account_id not in self.known_account_ids:
            if account_id not in self.warned_unknown_accounts:
                logger.warning(f"Row {row_num}: Unknown Account ID '{account_id}'")
                self.warned_unknown_accounts.add(account_id)
            self.unknown_accounts_count += 1
            return False

        # 5. Blank service
        if not service:
            logger.warning(f"Row {row_num}: Blank service name")
            return False

        # 6. Blank region
        if not region:
            logger.warning(f"Row {row_num}: Blank region name")
            return False

        # 7. Blank currency
        if not currency:
            logger.warning(f"Row {row_num}: Blank currency")
            return False

        # 8. Cost validation (Reject empty, NaN, malformed. Accept negative numbers.)
        if not cost_str:
            logger.warning(f"Row {row_num}: Empty cost value")
            return False

        try:
            cost_val = Decimal(cost_str)
            if cost_val.is_nan():
                logger.warning(f"Row {row_num}: Cost is NaN")
                return False
        except Exception:
            logger.warning(f"Row {row_num}: Invalid cost value '{cost_str}'")
            return False

        # 9. Duplicate rows check
        key_tuple = (billing_period, account_id, service, region, currency)
        if key_tuple in self.seen_keys:
            logger.warning(f"Row {row_num}: Duplicate row detected for key {key_tuple}")
            self.duplicates_count += 1
            return False
        self.seen_keys.add(key_tuple)

        return True
