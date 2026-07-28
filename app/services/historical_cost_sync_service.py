import logging
from datetime import date, datetime
from typing import Any

from app.db.cost_models import CostSyncHistory
from app.db.database import SessionLocal

logger = logging.getLogger(__name__)


class HistoricalCostSyncService:
    """One-time historical bootstrap using the new S3 ETL pipeline."""

    def __init__(self, cost_service: Any = None) -> None:
        # Keep cost_service parameter for backward compatibility
        self._cost_service = cost_service

    def bootstrap_historical_costs(self) -> dict[str, Any]:
        logger.info("Starting historical S3 ETL bootstrap...")
        try:
            from app.etl.merge_service import run_etl_pipeline
            with SessionLocal() as session:
                stats = run_etl_pipeline(session)

            return {
                "months_downloaded": stats["billing_files_processed"],
                "months_skipped": stats["billing_files_skipped"],
                "records_inserted": stats["records_inserted"],
                "status": "success",
            }
        except Exception as exc:
            logger.error("Historical S3 ETL bootstrap failed: %s", exc)
            return {
                "months_downloaded": 0,
                "months_skipped": 0,
                "records_inserted": 0,
                "status": "failed",
            }
