"""AWS Cost Explorer service for the MVP."""

import logging
from typing import Any
from datetime import datetime
from calendar import monthrange


from botocore.exceptions import BotoCoreError, ClientError

from app.config import get_settings
from app.schemas.cost_schema import (
    MonthlyCost,
    MonthlyCostResponse,
    ServiceBreakdownResponse,
    ServiceCost,
    TotalCostResponse,
    CostByMonthResponse
)
from app.utils.aws_utils import get_cost_explorer_client
from app.utils.helpers import calculate_percentage, format_month_label, get_date_range_months, get_last_month_range, safe_float

settings = get_settings()

logger = logging.getLogger(__name__)


class CostExplorerService:
    """Small wrapper around AWS Cost Explorer for current/historical spend."""

    def __init__(self) -> None:
        self._client = get_cost_explorer_client(region=settings.ce_region)

    def _get_cost_and_usage(
        self,
        start: str,
        end: str,
        granularity: str = "MONTHLY",
        group_by: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "TimePeriod": {"Start": start, "End": end},
            "Granularity": granularity,
            "Metrics": ["UnblendedCost"],
        }
        if group_by:
            params["GroupBy"] = group_by

        try:
            return self._client.get_cost_and_usage(**params)
        except (ClientError, BotoCoreError) as exc:
            raise RuntimeError(f"AWS Cost Explorer error: {exc}") from exc

    def get_total_cost(self, start: str | None = None, end: str | None = None) -> TotalCostResponse:
        """Return total unblended cost for a period."""
        if not start or not end:
            start, end = get_last_month_range()

        response = self._get_cost_and_usage(start, end)
        total = 0.0
        unit = "USD"
        for item in response.get("ResultsByTime", []):
            metric = item.get("Total", {}).get("UnblendedCost", {})
            total += safe_float(metric.get("Amount"))
            unit = metric.get("Unit", unit)

        return TotalCostResponse(start=start, end=end, total_cost=round(total, 4), unit=unit)

    def get_service_breakdown(self, start: str | None = None, end: str | None = None) -> ServiceBreakdownResponse:
        """Return service-wise unblended cost breakdown."""
        if not start or not end:
            start, end = get_last_month_range()

        response = self._get_cost_and_usage(
            start,
            end,
            group_by=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )
        totals: dict[str, float] = {}
        unit = "USD"
        for item in response.get("ResultsByTime", []):
            for group in item.get("Groups", []):
                service = group["Keys"][0]
                metric = group.get("Metrics", {}).get("UnblendedCost", {})
                amount = safe_float(metric.get("Amount"))
                unit = metric.get("Unit", unit)
                totals[service] = totals.get(service, 0.0) + amount

        grand_total = sum(totals.values())
        services = [
            ServiceCost(
                service=name,
                amount=round(amount, 4),
                unit=unit,
                percentage=calculate_percentage(amount, grand_total),
            )
            for name, amount in sorted(totals.items(), key=lambda item: item[1], reverse=True)
            if amount > 0
        ]
        return ServiceBreakdownResponse(start=start, end=end, total_cost=round(grand_total, 4), unit=unit, services=services)

    def compare_months(self, months: int = 2) -> MonthlyCostResponse:
        """Compare monthly AWS costs over the requested historical range."""
        start, end = get_date_range_months(months)
        response = self._get_cost_and_usage(start, end, granularity="MONTHLY")
        results: list[MonthlyCost] = []
        unit = "USD"
        for item in response.get("ResultsByTime", []):
            metric = item.get("Total", {}).get("UnblendedCost", {})
            amount = safe_float(metric.get("Amount"))
            unit = metric.get("Unit", unit)
            results.append(MonthlyCost(month=format_month_label(item["TimePeriod"]["Start"]), total_cost=round(amount, 4), unit=unit))

        change_amount = 0.0
        change_percent = 0.0
        if len(results) >= 2:
            previous = results[-2].total_cost
            current = results[-1].total_cost
            change_amount = round(current - previous, 4)
            change_percent = calculate_percentage(change_amount, previous)

        return MonthlyCostResponse(months=results, change_amount=change_amount, change_percent=change_percent)

    def get_cost_by_month(
        self,
        month: str,
        year: int | None = None,
    ):
        """
        Supported formats:
        month=2026-05
        OR
        month=May&year=2026
        OR
        month=April
        (defaults to current year)
        """

        MONTH_MAP = {
            "january": 1,
            "february": 2,
            "march": 3,
            "april": 4,
            "may": 5,
            "june": 6,
            "july": 7,
            "august": 8,
            "september": 9,
            "october": 10,
            "november": 11,
            "december": 12,
        }

        try:

            # Format: 2026-05
            if "-" in month:
                year, month_num = map(int, month.split("-"))

            # Format: May
            else:
                month_num = MONTH_MAP.get(month.lower())

                if not month_num:
                    raise ValueError(
                        f"Invalid month name: {month}"
                    )

                if year is None:
                    year = datetime.now().year

            start_date = f"{year}-{month_num:02d}-01"

            if month_num == 12:
                end_date = f"{year + 1}-01-01"
            else:
                end_date = f"{year}-{month_num + 1:02d}-01"

            response = self._client.get_cost_and_usage(
                TimePeriod={
                    "Start": start_date,
                    "End": end_date,
                },
                Granularity="MONTHLY",
                Metrics=["UnblendedCost"],
            )

            amount = 0.0
            unit = "USD"

            for item in response.get(
                "ResultsByTime",
                [],
            ):
                metric = (
                    item.get("Total", {})
                    .get("UnblendedCost", {})
                )

                amount += float(
                    metric.get("Amount", 0)
                )

                unit = metric.get(
                    "Unit",
                    "USD",
                )

            return {
                "month": f"{year}-{month_num:02d}",
                "total_cost": round(
                    amount,
                    4,
                ),
                "unit": unit,
            }

        except Exception as exc:
            logger.exception(
                "Failed to fetch cost for month=%s year=%s",
                month,
                year,
            )

            raise ValueError(
                f"Unable to fetch cost for "
                f"month='{month}' "
                f"year='{year}': {exc}"
            ) from exc
