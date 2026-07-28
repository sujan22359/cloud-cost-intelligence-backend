import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.db.cost_models import CostSyncHistory, MonthlyCost
from app.db.database import SessionLocal

logger = logging.getLogger(__name__)


def is_billing_period_synced(billing_period: str) -> bool:
    """Check whether the requested billing period already exists in PostgreSQL."""
    with SessionLocal() as session:
        return session.query(MonthlyCost).filter(MonthlyCost.billing_period == billing_period).first() is not None


class CostExplorerSyncService:
    """Independent background sync for monthly cost data using the new S3 ETL pipeline."""

    def __init__(self, cost_service: Any = None) -> None:
        # Keep cost_service parameter for backward compatibility
        self._cost_service = cost_service

    def sync_if_needed(self) -> dict[str, Any]:
        """Synchronize the latest billing month using the ETL pipeline."""
        logger.info("Starting S3-based ETL sync...")
        start_time = datetime.utcnow()
        try:
            from app.etl.merge_service import run_etl_pipeline
            with SessionLocal() as session:
                stats = run_etl_pipeline(session)

            billing_period, _, _ = self._get_latest_completed_billing_period()
            duration = int((datetime.utcnow() - start_time).total_seconds())
            self._record_history(billing_period, "success", stats["records_inserted"], duration, None)

            # Query database to get total cost of this billing period
            with SessionLocal() as session:
                latest_record = session.query(MonthlyCost).filter(MonthlyCost.billing_period == billing_period).first()
                total_cost = latest_record.total_cost if latest_record else Decimal("0.00")

            return {
                "status": "success",
                "billing_period": billing_period,
                "total_cost": str(total_cost),
                "unit": "USD",
            }
        except Exception as exc:
            billing_period, _, _ = self._get_latest_completed_billing_period()
            duration = int((datetime.utcnow() - start_time).total_seconds())
            self._record_history(billing_period, "failed", 0, duration, str(exc))
            logger.error("S3 ETL sync failed: %s", exc)
            return {"status": "failed", "billing_period": billing_period, "error": str(exc)}

    def sync_latest_month(self) -> dict[str, Any]:
        """Backward-compatible wrapper for the legacy sync entry point."""
        return self.sync_if_needed()

    def _get_latest_completed_billing_period(self) -> tuple[str, str, str]:
        today = date.today()
        first_of_current_month = today.replace(day=1)
        last_day_previous_month = first_of_current_month - timedelta(days=1)
        start_date = last_day_previous_month.replace(day=1).strftime("%Y-%m-%d")
        end_date = first_of_current_month.strftime("%Y-%m-%d")
        billing_period = last_day_previous_month.replace(day=1).strftime("%Y-%m")
        return billing_period, start_date, end_date

    def _record_history(
        self,
        billing_period: str,
        status: str,
        records_inserted: int,
        duration_seconds: int,
        error_message: str | None,
    ) -> None:
        with SessionLocal() as session:
            session.add(
                CostSyncHistory(
                    billing_period=billing_period,
                    status=status,
                    records_inserted=records_inserted,
                    duration_seconds=duration_seconds,
                    error_message=error_message,
                )
            )
            session.commit()
