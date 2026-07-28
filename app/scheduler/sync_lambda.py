"""AWS Lambda handler and CLI runner for background Cost Explorer ETL synchronization."""

import logging
from typing import Any

from app.services.cost_sync_service import CostExplorerSyncService
from app.utils.logger import setup_logging

logger = logging.getLogger(__name__)


def sync_handler(event: dict[str, Any] | None = None, context: Any = None) -> dict[str, Any]:
    """AWS Lambda entry point for scheduled Cost Explorer sync.

    Args:
        event: Optional event payload from EventBridge or manual invocation.
        context: AWS Lambda context object.

    Returns:
        Dict with status, billing_period, total_cost, or error message.
    """
    setup_logging()
    logger.info("Starting background Cost Explorer ETL sync task...")
    try:
        service = CostExplorerSyncService()
        result = service.sync_if_needed()
        logger.info("Background Cost Explorer sync finished with status: %s", result.get("status"))
        return result
    except Exception as exc:
        logger.exception("Error executing background Cost Explorer sync: %s", exc)
        return {"status": "failed", "error": str(exc)}


if __name__ == "__main__":
    sync_handler()
