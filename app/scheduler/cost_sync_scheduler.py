import logging
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler

from app.services.cost_sync_service import CostExplorerSyncService

logger = logging.getLogger(__name__)


class CostExplorerScheduler:
    """Background scheduler for daily Cost Explorer sync checks."""

    def __init__(self, sync_service: CostExplorerSyncService | None = None) -> None:
        self._scheduler = BackgroundScheduler()
        self._sync_service = sync_service or CostExplorerSyncService()

    def start(self) -> None:
        if self._scheduler.running:
            return
        self._scheduler.add_job(self._sync_service.sync_if_needed, "cron", hour=2, minute=0, misfire_grace_time=3600)
        self._scheduler.start()
        logger.info("Scheduler started.")

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def run_once(self) -> dict[str, Any]:
        return self._sync_service.sync_if_needed()
