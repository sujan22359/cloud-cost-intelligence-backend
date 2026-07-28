"""Read-only dashboard cost endpoints backed by PostgreSQL snapshots."""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.schemas.cost_schema import (
    CostByMonthResponse,
    HistoricalBootstrapResponse,
    MonthlyCostResponse,
    ServiceBreakdownResponse,
    DimensionType,
)
from app.schemas.optimization_schema import OptimizationRecommendationResponse
from app.services.business_cost_service import BusinessCostService
from app.services.historical_cost_sync_service import HistoricalCostSyncService
from app.services.optimization_service import OptimizationService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Cost Explorer"])


def get_dashboard_cost_service() -> BusinessCostService:
    return BusinessCostService()


def get_historical_cost_sync_service() -> HistoricalCostSyncService:
    return HistoricalCostSyncService()


def get_optimization_service() -> OptimizationService:
    return OptimizationService()


async def _run_sync(func, *args):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, func, *args)


# ── Existing endpoints ──────────────────────────────────────────────────────────

@router.get("/monthly-cost", response_model=MonthlyCostResponse)
async def monthly_cost(
    months: int = Query(default=2, ge=1, le=24),
    product: str | None = Query(default=None),
    environment: str | None = Query(default=None),
    account: str | None = Query(default=None),
    region: str | None = Query(default=None),
    service: BusinessCostService = Depends(get_dashboard_cost_service),
) -> MonthlyCostResponse:
    """Return synchronized month-by-month cost data from PostgreSQL snapshot."""
    try:
        return await _run_sync(service.get_monthly_cost_response, months, product, None, environment, account, region)
    except (RuntimeError, ValueError) as exc:
        logger.error("Monthly cost retrieval failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/service-breakdown", response_model=ServiceBreakdownResponse)
async def service_breakdown(
    start: str | None = Query(default=None, description="Start date YYYY-MM-DD"),
    end: str | None = Query(default=None, description="End date YYYY-MM-DD, exclusive"),
    product: str | None = Query(default=None),
    environment: str | None = Query(default=None),
    account: str | None = Query(default=None),
    region: str | None = Query(default=None),
    billing_period: str | None = Query(default=None),
    service: BusinessCostService = Depends(get_dashboard_cost_service),
) -> ServiceBreakdownResponse:
    """Return service-wise cost breakdown from synchronized PostgreSQL data."""
    try:
        return await _run_sync(service.get_service_breakdown_response, start, end, product, None, environment, account, region, billing_period)
    except (RuntimeError, ValueError) as exc:
        logger.error("Service breakdown retrieval failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


MONTH_NAME_MAP = {
    "january": "01",
    "february": "02",
    "march": "03",
    "april": "04",
    "may": "05",
    "june": "06",
    "july": "07",
    "august": "08",
    "september": "09",
    "october": "10",
    "november": "11",
    "december": "12",
}

def _resolve_billing_period(month: str, year: int | None, service: BusinessCostService) -> str:
    if "-" in month:
        return month

    month_number = MONTH_NAME_MAP.get(month.strip().lower())
    if month_number is None:
        raise ValueError(f"Invalid month value '{month}'.")

    if year is not None:
        return f"{year}-{month_number:02d}"

    available_periods = service._query.get_available_periods()
    for period in available_periods:
        if period.endswith(f"-{month_number:02d}"):
            return period

    raise ValueError(f"No synchronized billing period found for month '{month}'.")


@router.get("/cost-by-month", response_model=CostByMonthResponse, summary="Get AWS cost for a specific month")
async def get_cost_by_month(
    month: str,
    year: int | None = None,
    cost_service: BusinessCostService = Depends(get_dashboard_cost_service),
):
    """Examples:

    /cost-by-month?month=2026-05

    /cost-by-month?month=May&year=2026

    /cost-by-month?month=April
    """
    try:
        billing_period = _resolve_billing_period(month, year, cost_service)
        return await _run_sync(
            cost_service.get_cost_by_month_response,
            billing_period,
        )
    except (RuntimeError, ValueError) as exc:
        logger.error("Cost-by-month retrieval failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post("/bootstrap-historical-costs", response_model=HistoricalBootstrapResponse)
async def bootstrap_historical_costs(
    sync_service: HistoricalCostSyncService = Depends(get_historical_cost_sync_service),
) -> HistoricalBootstrapResponse:
    """Initial deployment endpoint for historical Cost Explorer backfill."""
    try:
        result = await _run_sync(sync_service.bootstrap_historical_costs)
        return HistoricalBootstrapResponse(**result)
    except (RuntimeError, ValueError) as exc:
        logger.error("Historical bootstrap failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


# ── New analytics endpoints ─────────────────────────────────────────────────────

@router.get(
    "/analytics/trend",
    summary="Get all service costs grouped by billing period for trend charts",
    tags=["Analytics"],
)
async def analytics_trend(
    product: str | None = Query(default=None),
    environment: str | None = Query(default=None),
    account: str | None = Query(default=None),
    region: str | None = Query(default=None),
    service: BusinessCostService = Depends(get_dashboard_cost_service),
) -> dict:
    """
    Return all service costs grouped by billing period.

    Shape:
    {
      "periods": ["2026-01", "2026-02", ...],
      "services": {
        "Amazon RDS": {"2026-01": 95.0, "2026-02": 107.0},
        ...
      }
    }

    Used by the Analytics Service Trend Chart.
    """
    try:
        result = await _run_sync(service.get_all_service_costs_by_period, product, None, environment, account, region)
        if result is None:
            return {"analysis": "service_trend", "periods": [], "services": {}}
        return result
    except (RuntimeError, ValueError) as exc:
        logger.error("Analytics trend retrieval failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get(
    "/analytics/comparison",
    summary="Get enriched month-over-month comparison",
    tags=["Analytics"],
)
async def analytics_comparison(
    period_a: str | None = Query(default=None, description="Earlier billing period YYYY-MM"),
    period_b: str | None = Query(default=None, description="Later billing period YYYY-MM"),
    product: str | None = Query(default=None),
    environment: str | None = Query(default=None),
    account: str | None = Query(default=None),
    region: str | None = Query(default=None),
    billing_period: str | None = Query(default=None),
    service: BusinessCostService = Depends(get_dashboard_cost_service),
) -> dict:
    """
    Return an enriched month-over-month comparison including:
    - Total spend for each period
    - Dollar difference and percentage change
    - Highest increased and decreased service
    - Per-service cost deltas
    - Human-readable summary

    Defaults to latest two available periods if not specified.
    """
    try:
        actual_period_b = period_b or billing_period
        result = await _run_sync(service.compare_months, actual_period_b, period_a, product, None, environment, account, region)
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No billing data available for comparison.",
            )
        return result
    except (RuntimeError, ValueError) as exc:
        logger.error("Analytics comparison retrieval failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


# ── Optimization endpoint ───────────────────────────────────────────────────────

@router.get(
    "/optimization/recommendations",
    response_model=OptimizationRecommendationResponse,
    summary="Get cost optimization recommendations from PostgreSQL billing data",
    tags=["Optimization"],
)
async def optimization_recommendations(
    product: str | None = Query(default=None),
    environment: str | None = Query(default=None),
    account: str | None = Query(default=None),
    region: str | None = Query(default=None),
    billing_period: str | None = Query(default=None),
    opt_service: OptimizationService = Depends(get_optimization_service),
) -> OptimizationRecommendationResponse:
    """
    Generate data-driven cost optimization recommendations.

    All recommendations are derived from actual billing data in PostgreSQL.
    Includes:
    - High-growth services (significant MoM cost increases)
    - Top cost drivers (highest absolute spend)
    - Potentially idle resources (near-zero cost services)

    Each recommendation includes: issue, reason, business impact,
    estimated savings, recommended action, and priority (HIGH/MEDIUM/LOW).
    """
    try:
        return await _run_sync(opt_service.generate_recommendations, product, None, environment, account, region, billing_period)
    except (RuntimeError, ValueError) as exc:
        logger.error("Optimization recommendations failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/analytics/dashboard-kpis", summary="Get dashboard key business performance indicators")
async def get_dashboard_kpis(
    billing_period: str | None = Query(default=None),
    product: str | None = Query(default=None),
    team: str | None = Query(default=None, deprecated=True),
    environment: str | None = Query(default=None),
    account: str | None = Query(default=None),
    region: str | None = Query(default=None),
    service: BusinessCostService = Depends(get_dashboard_cost_service),
):
    try:
        # Run breakdowns in parallel executor
        loop = asyncio.get_running_loop()
        
        products = await loop.run_in_executor(None, service.get_dimension_breakdown, DimensionType.PRODUCT, billing_period, product, team, environment, account, region)
        teams = await loop.run_in_executor(None, service.get_dimension_breakdown, DimensionType.TEAM, billing_period, product, team, environment, account, region)
        environments = await loop.run_in_executor(None, service.get_dimension_breakdown, DimensionType.ENVIRONMENT, billing_period, product, team, environment, account, region)
        regions = await loop.run_in_executor(None, service.get_dimension_breakdown, DimensionType.REGION, billing_period, product, team, environment, account, region)
        accounts = await loop.run_in_executor(None, service.get_dimension_breakdown, DimensionType.ACCOUNT, billing_period, product, team, environment, account, region)

        highest_region = regions[0] if regions else {"region": "N/A", "cost": 0.0}
        highest_account = accounts[0] if accounts else {"account_name": "N/A", "cost": 0.0}

        # Calculate MoM growth for products to find fastest growing
        latest_period = billing_period or service._query.get_latest_billing_period()
        prev_period = service._query._previous_period(latest_period) if latest_period else None

        fastest_product = {"product": "N/A", "growth_pct": 0.0}
        fastest_team = {"team": "N/A", "growth_pct": 0.0}

        if latest_period and prev_period:
            # Products MoM
            prod_now = {p["product"]: p["cost"] for p in products}
            prod_prev = {p["product"]: p["cost"] for p in service.get_dimension_breakdown(DimensionType.PRODUCT, prev_period, product, team, environment, account, region)}
            max_prod_growth = -999999.0
            for name, cost_now in prod_now.items():
                cost_prev = prod_prev.get(name, 0.0)
                if cost_prev > 0:
                    pct = ((cost_now - cost_prev) / cost_prev) * 100
                    if pct > max_prod_growth:
                        max_prod_growth = pct
                        fastest_product = {"product": name, "growth_pct": round(pct, 1)}

            # Teams MoM
            team_now = {t["team"]: t["cost"] for t in teams}
            team_prev = {t["team"]: t["cost"] for t in service.get_dimension_breakdown(DimensionType.TEAM, prev_period, product, team, environment, account, region)}
            max_team_growth = -999999.0
            for name, cost_now in team_now.items():
                cost_prev = team_prev.get(name, 0.0)
                if cost_prev > 0:
                    pct = ((cost_now - cost_prev) / cost_prev) * 100
                    if pct > max_team_growth:
                        max_team_growth = pct
                        fastest_team = {"team": name, "growth_pct": round(pct, 1)}

        return {
            "products": products,
            "teams": teams,
            "environments": environments,
            "highest_region": highest_region,
            "highest_account": highest_account,
            "fastest_growing_product": fastest_product,
            "fastest_growing_team": fastest_team
        }
    except Exception as exc:
        logger.error("Dashboard KPIs failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/analytics/dimension/breakdown", summary="Get cost breakdown for a business dimension")
async def get_dimension_breakdown_route(
    dimension: DimensionType,
    billing_period: str | None = Query(default=None),
    product: str | None = Query(default=None),
    team: str | None = Query(default=None, deprecated=True),
    environment: str | None = Query(default=None),
    account: str | None = Query(default=None),
    region: str | None = Query(default=None),
    service: BusinessCostService = Depends(get_dashboard_cost_service),
):
    try:
        return await _run_sync(service.get_dimension_breakdown, dimension, billing_period, product, team, environment, account, region)
    except Exception as exc:
        logger.error("Dimension breakdown failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/analytics/dimension/trend", summary="Get monthly trend for an item in a business dimension")
async def get_dimension_trend_route(
    dimension: DimensionType,
    item: str,
    limit: int = Query(default=6, ge=1, le=24),
    product: str | None = Query(default=None),
    team: str | None = Query(default=None, deprecated=True),
    environment: str | None = Query(default=None),
    account: str | None = Query(default=None),
    region: str | None = Query(default=None),
    service: BusinessCostService = Depends(get_dashboard_cost_service),
):
    try:
        return await _run_sync(service.get_dimension_trend, dimension, item, limit, product, team, environment, account, region)
    except Exception as exc:
        logger.error("Dimension trend failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/analytics/dimension/comparison", summary="Compare two items in a business dimension")
async def get_dimension_comparison_route(
    dimension: DimensionType,
    item_a: str,
    item_b: str,
    billing_period: str | None = Query(default=None),
    product: str | None = Query(default=None),
    team: str | None = Query(default=None, deprecated=True),
    environment: str | None = Query(default=None),
    account: str | None = Query(default=None),
    region: str | None = Query(default=None),
    service: BusinessCostService = Depends(get_dashboard_cost_service),
):
    try:
        result = await _run_sync(service.get_dimension_comparison, dimension, item_a, item_b, billing_period, product, team, environment, account, region)
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comparison data not found")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Dimension comparison failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/analytics/shared-infrastructure", summary="Get shared infrastructure cost breakdown")
async def get_shared_infrastructure_route(
    billing_period: str | None = Query(default=None),
    product: str | None = Query(default=None),
    environment: str | None = Query(default=None),
    region: str | None = Query(default=None),
    account: str | None = Query(default=None),
    service: BusinessCostService = Depends(get_dashboard_cost_service),
):
    try:
        result = await _run_sync(
            service.get_shared_infrastructure_analysis,
            billing_period,
            product,
            environment,
            region,
            account
        )
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shared infrastructure data not found")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Shared infrastructure analysis failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/analytics/developer-accounts", summary="Get developer accounts cost breakdown")
async def get_developer_accounts_route(
    billing_period: str | None = Query(default=None),
    product: str | None = Query(default=None),
    environment: str | None = Query(default=None),
    region: str | None = Query(default=None),
    account: str | None = Query(default=None),
    service: BusinessCostService = Depends(get_dashboard_cost_service),
):
    try:
        result = await _run_sync(
            service.get_developer_analysis,
            billing_period,
            product,
            environment,
            region,
            account
        )
        if result is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Developer accounts data not found")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Developer accounts analysis failed: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
