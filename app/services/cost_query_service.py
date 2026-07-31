"""Read-only PostgreSQL access for Cost Explorer snapshots."""

from datetime import date
import logging
from decimal import Decimal
from typing import Any

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.db.cost_models import AccountMaster, MonthlyCost, ServiceCost
from app.db.database import SessionLocal
from app.schemas.cost_schema import MonthlyCost as MonthlyCostSchema
from app.schemas.cost_schema import MonthlyCostResponse, ServiceBreakdownResponse, ServiceCost as ServiceCostSchema, DimensionType

logger = logging.getLogger(__name__)


class CostQueryService:
    """Read-only access to persisted Cost Explorer data."""

    def __init__(self, session_factory: Any | None = None) -> None:
        self._session_factory = session_factory or SessionLocal

    def get_total_month_cost(self, billing_period: str | None = None) -> dict[str, Any] | None:
        session = self._get_session()
        if session is None:
            return None
        with session as session_obj:
            record = self._get_monthly_record(session_obj, billing_period)
            if record is None:
                return None
            return {
                "analysis": "total_cost",
                "billing_period": record.billing_period,
                "total_cost": self._to_float(record.total_cost),
            }

    def get_latest_month_cost(self) -> dict[str, Any] | None:
        session = self._get_session()
        if session is None:
            return None
        with session as session_obj:
            record = self._latest_monthly_record(session_obj)
            if record is None:
                return None
            return {
                "analysis": "latest_cost",
                "billing_period": record.billing_period,
                "total_cost": self._to_float(record.total_cost),
            }

    def get_service_cost(self, service: str, billing_period: str | None = None) -> dict[str, Any] | None:
        session = self._get_session()
        if session is None:
            return None
        with session as session_obj:
            period = billing_period or self._latest_period(session_obj)
            if period is None:
                return None
            
            from app.services.business_cost_service import resolve_service_name_alias, normalize_business_service_name
            target_business_name = resolve_service_name_alias(service)
            
            # Query all service records for this period
            rows = session_obj.query(ServiceCost).filter(ServiceCost.billing_period == period).all()
            
            matching_rows = []
            for row in rows:
                if row.service_name:
                    norm = normalize_business_service_name(row.service_name)
                    if norm.lower() == target_business_name.lower():
                        matching_rows.append(row)
            
            if not matching_rows:
                return None
                
            total_cost = sum(self._to_float(r.cost) for r in matching_rows)
            return {
                "analysis": "service_cost",
                "billing_period": period,
                "service": target_business_name,
                "cost": round(total_cost, 4),
            }

    def get_top_services(self, billing_period: str | None = None, limit: int = 5) -> dict[str, Any] | None:
        session = self._get_session()
        if session is None:
            return None
        with session as session_obj:
            period = billing_period or self._latest_period(session_obj)
            if period is None:
                return None
            rows = (
                session_obj.query(ServiceCost)
                .filter(ServiceCost.billing_period == period)
                .order_by(ServiceCost.cost.desc())
                .limit(limit)
                .all()
            )
            return {
                "analysis": "top_services",
                "billing_period": period,
                "top_services": [
                    {"service": row.service_name, "cost": self._to_float(row.cost)}
                    for row in rows
                ],
            }

    def get_highest_service(self, billing_period: str | None = None) -> dict[str, Any] | None:
        session = self._get_session()
        if session is None:
            return None
        with session as session_obj:
            period = billing_period or self._latest_period(session_obj)
            if period is None:
                return None
            row = (
                session_obj.query(ServiceCost)
                .filter(ServiceCost.billing_period == period)
                .order_by(ServiceCost.cost.desc())
                .first()
            )
            if row is None:
                return None
            return {
                "analysis": "highest",
                "billing_period": period,
                "highest_service": row.service_name,
                "highest_cost": self._to_float(row.cost),
            }

    def get_lowest_service(self, billing_period: str | None = None) -> dict[str, Any] | None:
        session = self._get_session()
        if session is None:
            return None
        with session as session_obj:
            period = billing_period or self._latest_period(session_obj)
            if period is None:
                return None
            row = (
                session_obj.query(ServiceCost)
                .filter(ServiceCost.billing_period == period)
                .order_by(ServiceCost.cost.asc())
                .first()
            )
            if row is None:
                return None
            return {
                "analysis": "lowest",
                "billing_period": period,
                "lowest_service": row.service_name,
                "lowest_cost": self._to_float(row.cost),
            }

    def compare_months(
        self,
        current_period: str | None = None,
        previous_period: str | None = None,
        product: str | None = None,
        team: str | None = None,
        environment: str | None = None,
        account: str | None = None,
        region: str | None = None,
    ) -> dict[str, Any] | None:
        """Return an enriched month-over-month comparison with per-service deltas."""
        session = self._get_session()
        if session is None:
            return None
        with session as session_obj:
            if current_period == "undefined" or current_period == "":
                current_period = None
            if previous_period == "undefined" or previous_period == "":
                previous_period = None

            current = current_period or self._latest_period(session_obj)
            if current is None:
                return None

            if previous_period:
                previous = previous_period
            else:
                cand_prev = self._previous_period(current)
                from app.db.cost_models import MonthlyCost
                all_months = [row[0] for row in session_obj.query(MonthlyCost.billing_period).order_by(MonthlyCost.billing_period.asc()).all()]
                if all_months and current == all_months[0]:
                    previous = None
                else:
                    previous = cand_prev

            if product or team or environment or account or region:
                # Sum cost from ServiceCost
                current_cost_query = session_obj.query(func.sum(ServiceCost.cost)).filter(ServiceCost.billing_period == current)
                current_cost_query = self._apply_filters(current_cost_query, product=product, team=team, environment=environment, account=account, region=region)
                cost_current = self._to_float(current_cost_query.scalar()) or 0.0
                
                if previous:
                    previous_cost_query = session_obj.query(func.sum(ServiceCost.cost)).filter(ServiceCost.billing_period == previous)
                    previous_cost_query = self._apply_filters(previous_cost_query, product=product, team=team, environment=environment, account=account, region=region)
                    cost_previous = self._to_float(previous_cost_query.scalar()) or 0.0
                else:
                    cost_previous = None
            else:
                current_row = self._get_monthly_record(session_obj, current)
                previous_row = self._get_monthly_record(session_obj, previous) if previous else None

                if current_row is None:
                    return None

                cost_current = self._to_float(current_row.total_cost) or 0.0
                cost_previous = self._to_float(previous_row.total_cost) if previous_row else None

            difference = round(cost_current - (cost_previous or 0.0), 4) if cost_previous is not None else cost_current
            pct_change = (
                self._calculate_percentage(difference, cost_previous)
                if cost_previous and difference is not None
                else 0.0
            )

            # Per-service comparison
            service_deltas = self._compare_service_costs(
                session_obj, current, previous,
                product=product, team=team, environment=environment, account=account, region=region
            )

            highest_increased: dict[str, Any] | None = None
            highest_decreased: dict[str, Any] | None = None

            if service_deltas:
                increases = [s for s in service_deltas if s["change"] > 0]
                decreases = [s for s in service_deltas if s["change"] < 0]
                if increases:
                    highest_increased = max(increases, key=lambda s: s["change"])
                if decreases:
                    highest_decreased = min(decreases, key=lambda s: s["change"])

            summary = self._build_comparison_summary(
                previous, current, cost_previous, cost_current, pct_change, highest_increased
            )

            return {
                "analysis": "compare_months",
                "period_a": previous,
                "period_b": current,
                "cost_a": cost_previous,
                "cost_b": cost_current,
                "difference": difference,
                "percentage_change": pct_change,
                "highest_increased_service": highest_increased,
                "highest_decreased_service": highest_decreased,
                "service_deltas": service_deltas,
                # Legacy-compatible fields
                "billing_period": current,
                "comparison": [
                    {"billing_period": previous, "total_cost": cost_previous},
                    {"billing_period": current, "total_cost": cost_current},
                ],
                "summary": summary,
            }

    def _compare_service_costs(
        self,
        session: Session,
        current_period: str,
        previous_period: str,
        product: str | None = None,
        team: str | None = None,
        environment: str | None = None,
        account: str | None = None,
        region: str | None = None,
    ) -> list[dict[str, Any]]:
        """Join service costs for two periods and compute per-service deltas."""
        current_q = session.query(ServiceCost).filter(ServiceCost.billing_period == current_period)
        current_q = self._apply_filters(current_q, product=product, team=team, environment=environment, account=account, region=region)
        current_rows = {
            row.service_name: self._to_float(row.cost) or 0.0
            for row in current_q.all()
        }

        previous_rows = {}
        if previous_period:
            previous_q = session.query(ServiceCost).filter(ServiceCost.billing_period == previous_period)
            previous_q = self._apply_filters(previous_q, product=product, team=team, environment=environment, account=account, region=region)
            previous_rows = {
                row.service_name: self._to_float(row.cost) or 0.0
                for row in previous_q.all()
            }

        all_services = set(current_rows.keys()) | set(previous_rows.keys())
        deltas: list[dict[str, Any]] = []
        for service in all_services:
            cost_now = current_rows.get(service, 0.0)
            cost_prev = previous_rows.get(service, 0.0)
            change = round(cost_now - cost_prev, 4)
            change_pct = self._calculate_percentage(change, cost_prev) if cost_prev else None
            deltas.append({
                "service": service,
                "cost_a": cost_prev,
                "cost_b": cost_now,
                "change": change,
                "change_pct": change_pct,
            })

        return sorted(deltas, key=lambda d: abs(d["change"]), reverse=True)

    @staticmethod
    def _build_comparison_summary(
        period_a: str | None,
        period_b: str,
        cost_a: float | None,
        cost_b: float,
        pct_change: float | None,
        highest_increased: dict[str, Any] | None,
    ) -> str:
        if cost_a is None:
            return f"Spend for {period_b} was ${cost_b:,.2f}. No prior month data available for comparison."
        direction = "increased" if pct_change and pct_change > 0 else "decreased" if pct_change and pct_change < 0 else "held steady"
        pct_str = f"{abs(pct_change):.1f}%" if pct_change is not None else ""
        summary = f"Spend {direction} {pct_str} from {period_a} (${cost_a:,.2f}) to {period_b} (${cost_b:,.2f})."
        if highest_increased:
            summary += (
                f" {highest_increased['service']} drove the largest increase"
                f" (+${highest_increased['change']:,.2f})."
            )
        return summary

    def get_month_summary(self, billing_period: str | None = None) -> dict[str, Any] | None:
        session = self._get_session()
        if session is None:
            return None
        with session as session_obj:
            period = billing_period or self._latest_period(session_obj)
            if period is None:
                return None
            month_row = self._get_monthly_record(session_obj, period)
            top_rows = (
                session_obj.query(ServiceCost)
                .filter(ServiceCost.billing_period == period)
                .order_by(ServiceCost.cost.desc())
                .limit(5)
                .all()
            )
            if month_row is None:
                return None
            return {
                "analysis": "summary",
                "billing_period": period,
                "total_cost": self._to_float(month_row.total_cost),
                "top_services": [
                    {"service": row.service_name, "cost": self._to_float(row.cost)}
                    for row in top_rows
                ],
            }

    def get_available_periods(self) -> list[str]:
        session = self._get_session()
        if session is None:
            return []
        with session as session_obj:
            rows = session_obj.query(MonthlyCost.billing_period).order_by(MonthlyCost.billing_period.desc()).all()
            return [row[0] for row in rows]

    def get_latest_billing_period(self) -> str | None:
        session = self._get_session()
        if session is None:
            return None
        with session as session_obj:
            return self._latest_period(session_obj)

    def get_monthly_record_data(self, billing_period: str | None = None) -> dict[str, Any] | None:
        session = self._get_session()
        if session is None:
            return None
        with session as session_obj:
            record = self._get_monthly_record(session_obj, billing_period)
            if record is None:
                return None
            return {
                "billing_period": record.billing_period,
                "start_date": self._date_to_iso(record.start_date),
                "end_date": self._date_to_iso(record.end_date),
                "total_cost": round(self._to_float(record.total_cost) or 0.0, 4),
                "unit": record.currency or "USD",
            }

    def get_service_rows_data(
        self,
        billing_period: str | None = None,
        product: str | None = None,
        team: str | None = None,
        environment: str | None = None,
        account: str | None = None,
        region: str | None = None,
    ) -> list[dict[str, Any]]:
        session = self._get_session()
        if session is None:
            return []
        with session as session_obj:
            period = billing_period or self._latest_period(session_obj)
            if period is None:
                return []
            query = session_obj.query(ServiceCost).filter(ServiceCost.billing_period == period)
            query = self._apply_filters(query, product=product, team=team, environment=environment, account=account, region=region)
            rows = query.order_by(ServiceCost.cost.desc()).all()
            return [
                {
                    "billing_period": period,
                    "service": row.service_name,
                    "amount": round(self._to_float(row.cost) or 0.0, 4),
                    "unit": row.currency or "USD",
                }
                for row in rows
            ]

    def get_available_service_names(self, billing_period: str | None = None) -> list[str]:
        session = self._get_session()
        if session is None:
            return []
        with session as session_obj:
            query = session_obj.query(ServiceCost.service_name).distinct().order_by(ServiceCost.service_name.asc())
            if billing_period is not None:
                query = query.filter(ServiceCost.billing_period == billing_period)
            return [row[0] for row in query.all() if row[0]]

    def get_monthly_trend(self, limit: int = 6) -> dict[str, Any] | None:
        session = self._get_session()
        if session is None:
            return None
        with session as session_obj:
            rows = (
                session_obj.query(MonthlyCost)
                .order_by(MonthlyCost.billing_period.desc())
                .limit(limit)
                .all()
            )
            if not rows:
                return None
            return {
                "analysis": "trend",
                "trend": [
                    {"billing_period": row.billing_period, "total_cost": self._to_float(row.total_cost)}
                    for row in reversed(rows)
                ],
            }

    def get_monthly_average(self) -> dict[str, Any] | None:
        """Return the average monthly spend across all available periods."""
        session = self._get_session()
        if session is None:
            return None
        with session as session_obj:
            rows = session_obj.query(MonthlyCost).order_by(MonthlyCost.billing_period.asc()).all()
            if not rows:
                return None
            costs = [self._to_float(row.total_cost) or 0.0 for row in rows]
            avg = sum(costs) / len(costs)
            return {
                "analysis": "monthly_average",
                "months_counted": len(costs),
                "average_cost": round(avg, 4),
                "min_cost": round(min(costs), 4),
                "max_cost": round(max(costs), 4),
                "periods": [row.billing_period for row in rows],
            }

    def get_year_summary(self, year: int) -> dict[str, Any] | None:
        """Aggregate spend for all months in the given year."""
        session = self._get_session()
        if session is None:
            return None
        with session as session_obj:
            rows = (
                session_obj.query(MonthlyCost)
                .filter(MonthlyCost.billing_period.like(f"{year}-%"))
                .order_by(MonthlyCost.billing_period.asc())
                .all()
            )
            if not rows:
                return None
            total = sum(self._to_float(row.total_cost) or 0.0 for row in rows)
            return {
                "analysis": "yearly_summary",
                "year": year,
                "total_cost": round(total, 4),
                "months_available": len(rows),
                "months": [
                    {"billing_period": row.billing_period, "total_cost": self._to_float(row.total_cost)}
                    for row in rows
                ],
            }

    def get_all_service_costs_by_period(
        self,
        product: str | None = None,
        team: str | None = None,
        environment: str | None = None,
        account: str | None = None,
        region: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Return all service costs grouped by billing period for analytics trend charts.
        Shape: { periods: [...], services: { service_name: { period: cost } } }
        """
        session = self._get_session()
        if session is None:
            return None
        with session as session_obj:
            periods = [
                row[0]
                for row in session_obj.query(MonthlyCost.billing_period)
                .order_by(MonthlyCost.billing_period.asc())
                .all()
            ]
            if not periods:
                return None

            query = session_obj.query(ServiceCost).filter(ServiceCost.billing_period.in_(periods))
            query = self._apply_filters(query, product=product, team=team, environment=environment, account=account, region=region)
            all_rows = query.order_by(ServiceCost.billing_period.asc(), ServiceCost.cost.desc()).all()

            # Group by service
            service_map: dict[str, dict[str, float]] = {}
            for row in all_rows:
                if row.service_name not in service_map:
                    service_map[row.service_name] = {}
                service_map[row.service_name][row.billing_period] = service_map[row.service_name].get(row.billing_period, 0.0) + (self._to_float(row.cost) or 0.0)

            # Round costs
            for sname in service_map:
                for p in service_map[sname]:
                    service_map[sname][p] = round(service_map[sname][p], 4)

            return {
                "analysis": "service_trend",
                "periods": periods,
                "services": service_map,
            }

    def get_monthly_cost_response(
        self,
        months: int = 2,
        product: str | None = None,
        team: str | None = None,
        environment: str | None = None,
        account: str | None = None,
        region: str | None = None,
    ) -> MonthlyCostResponse:
        session = self._get_session()
        if session is None:
            return MonthlyCostResponse(months=[], change_amount=0.0, change_percent=0.0)

        with session as session_obj:
            if product or team or environment or account or region:
                # Sum cost from ServiceCost grouped by billing_period
                query = session_obj.query(
                    ServiceCost.billing_period,
                    func.sum(ServiceCost.cost).label("total_cost")
                )
                query = self._apply_filters(query, product=product, team=team, environment=environment, account=account, region=region)
                rows = (
                    query.group_by(ServiceCost.billing_period)
                    .order_by(ServiceCost.billing_period.desc())
                    .limit(months)
                    .all()
                )
                response_months = [
                    MonthlyCostSchema(
                        month=row.billing_period,
                        total_cost=round(self._to_float(row.total_cost) or 0.0, 4),
                        unit="USD",
                    )
                    for row in reversed(rows)
                ]
            else:
                rows = (
                    session_obj.query(MonthlyCost)
                    .order_by(MonthlyCost.billing_period.desc())
                    .limit(months)
                    .all()
                )
                if not rows:
                    return MonthlyCostResponse(months=[], change_amount=0.0, change_percent=0.0)

                ordered_rows = list(reversed(rows))
                response_months = [
                    MonthlyCostSchema(
                        month=row.billing_period,
                        total_cost=round(self._to_float(row.total_cost) or 0.0, 4),
                        unit=row.currency or "USD",
                    )
                    for row in ordered_rows
                ]

            change_amount = 0.0
            change_percent = 0.0
            if len(response_months) >= 2:
                previous = response_months[-2].total_cost
                current = response_months[-1].total_cost
                change_amount = round(current - previous, 4)
                change_percent = self._calculate_percentage(change_amount, previous)

            return MonthlyCostResponse(
                months=response_months,
                change_amount=change_amount,
                change_percent=change_percent,
            )

    def get_service_breakdown_response(
        self,
        start: str | None = None,
        end: str | None = None,
        product: str | None = None,
        team: str | None = None,
        environment: str | None = None,
        account: str | None = None,
        region: str | None = None,
        billing_period: str | None = None,
    ) -> ServiceBreakdownResponse:
        session = self._get_session()
        if session is None:
            return ServiceBreakdownResponse(start="", end="", total_cost=0.0, unit="USD", services=[])

        with session as session_obj:
            if billing_period:
                monthly_record = self._get_monthly_record(session_obj, billing_period)
            else:
                monthly_record = self._resolve_monthly_record_for_range(session_obj, start, end)

            if monthly_record is None:
                return ServiceBreakdownResponse(
                    start=start or "",
                    end=end or "",
                    total_cost=0.0,
                    unit="USD",
                    services=[],
                )

            # Query ServiceCost with filters
            query = session_obj.query(ServiceCost).filter(ServiceCost.billing_period == monthly_record.billing_period)
            query = self._apply_filters(query, product=product, team=team, environment=environment, account=account, region=region)
            service_rows = query.order_by(ServiceCost.cost.desc()).all()

            # If filters are active, total cost is the sum of filtered service rows
            if product or team or environment or account or region:
                total_cost = sum(self._to_float(row.cost) or 0.0 for row in service_rows)
            else:
                total_cost = self._to_float(monthly_record.total_cost) or 0.0

            services = [
                ServiceCostSchema(
                    service=row.service_name,
                    amount=round(self._to_float(row.cost) or 0.0, 4),
                    unit=row.currency or monthly_record.currency or "USD",
                    percentage=self._calculate_percentage(self._to_float(row.cost) or 0.0, total_cost),
                )
                for row in service_rows
                if (self._to_float(row.cost) or 0.0) > 0
            ]

            return ServiceBreakdownResponse(
                start=self._date_to_iso(monthly_record.start_date),
                end=self._date_to_iso(monthly_record.end_date),
                total_cost=round(total_cost, 4),
                unit=monthly_record.currency or "USD",
                services=services,
            )

    def _get_session(self) -> Any | None:
        try:
            return self._session_factory()
        except Exception:
            return None

    def _get_monthly_record(self, session: Session, billing_period: str | None) -> MonthlyCost | None:
        period = billing_period or self._latest_period(session)
        if period is None:
            return None
        return session.query(MonthlyCost).filter(MonthlyCost.billing_period == period).first()

    def _get_service_record(self, session: Session, service: str, billing_period: str | None) -> ServiceCost | None:
        period = billing_period or self._latest_period(session)
        if period is None or not service:
            return None
        return (
            session.query(ServiceCost)
            .filter(ServiceCost.billing_period == period, func.lower(ServiceCost.service_name) == service.lower())
            .first()
        )

    def _latest_monthly_record(self, session: Session) -> MonthlyCost | None:
        return session.query(MonthlyCost).order_by(MonthlyCost.billing_period.desc()).first()

    def _latest_period(self, session: Session) -> str | None:
        record = self._latest_monthly_record(session)
        return record.billing_period if record else None

    def _resolve_monthly_record_for_range(
        self,
        session: Session,
        start: str | None,
        end: str | None,
    ) -> MonthlyCost | None:
        if start and end:
            return (
                session.query(MonthlyCost)
                .filter(
                    MonthlyCost.start_date == date.fromisoformat(start),
                    MonthlyCost.end_date == date.fromisoformat(end),
                )
                .first()
            )
        return self._latest_monthly_record(session)

    @staticmethod
    def _previous_period(period: str) -> str:
        year, month = map(int, period.split("-"))
        if month == 1:
            return f"{year - 1}-12"
        return f"{year}-{month - 1:02d}"

    @staticmethod
    def _to_float(value: Decimal | None) -> float | None:
        return float(value) if value is not None else None

    @staticmethod
    def _calculate_percentage(amount: float, total: float) -> float:
        if total == 0:
            return 0.0
        return round((amount / total) * 100, 1)

    @staticmethod
    def _date_to_iso(value: date | None) -> str:
        return value.isoformat() if value is not None else ""

    @staticmethod
    def _apply_filters(
        query,
        billing_period: str | None = None,
        product: str | None = None,
        team: str | None = None,
        environment: str | None = None,
        account: str | None = None,
        region: str | None = None,
    ):
        if billing_period:
            query = query.filter(ServiceCost.billing_period == billing_period)
        if product:
            query = query.filter(ServiceCost.product == product)
        if team:
            query = query.filter(ServiceCost.team == team)
        if environment:
            query = query.filter(ServiceCost.environment == environment)
        if account:
            query = query.filter((ServiceCost.account_name == account) | (ServiceCost.account_id == account))
        if region:
            query = query.filter(ServiceCost.region == region)
        return query

    def get_dimension_breakdown(
        self,
        dimension: DimensionType,
        billing_period: str | None = None,
        product: str | None = None,
        team: str | None = None,
        environment: str | None = None,
        account: str | None = None,
        region: str | None = None,
    ) -> list[dict[str, Any]]:
        session = self._get_session()
        if session is None:
            return []
        with session as session_obj:
            period = billing_period or self._latest_period(session_obj)
            if not period:
                return []
            
            # Map dimension to model columns
            if dimension == DimensionType.PRODUCT:
                col = ServiceCost.product
                group_by_cols = [ServiceCost.product]
            elif dimension == DimensionType.TEAM:
                col = ServiceCost.team
                group_by_cols = [ServiceCost.team]
            elif dimension == DimensionType.ENVIRONMENT:
                col = ServiceCost.environment
                group_by_cols = [ServiceCost.environment]
            elif dimension == DimensionType.REGION:
                col = ServiceCost.region
                group_by_cols = [ServiceCost.region]
            effective_acc_name = func.coalesce(AccountMaster.account_name, ServiceCost.account_name)

            if dimension == DimensionType.ACCOUNT:
                group_by_cols = [ServiceCost.account_id, effective_acc_name]
                query = session_obj.query(
                    ServiceCost.account_id,
                    effective_acc_name.label("account_name"),
                    func.sum(ServiceCost.cost).label("cost")
                ).outerjoin(
                    AccountMaster, ServiceCost.account_id == AccountMaster.account_id
                )
            else:
                query = session_obj.query(
                    col,
                    func.sum(ServiceCost.cost).label("cost")
                )

            # Apply filters
            query = self._apply_filters(
                query,
                billing_period=period,
                product=product,
                team=team,
                environment=environment,
                account=account,
                region=region
            )

            if dimension == DimensionType.PRODUCT:
                query = query.filter(ServiceCost.product.in_(["SafeStart", "AccuTrain"]))
            elif dimension == DimensionType.ENVIRONMENT:
                query = query.filter(ServiceCost.environment.in_(["QA", "UAT", "Production", "Development"]))

            query = query.group_by(*group_by_cols).order_by(func.sum(ServiceCost.cost).desc())
            results = query.all()

            if dimension == DimensionType.ACCOUNT:
                account_map: dict[str, dict[str, Any]] = {}
                # Pre-populate all known accounts from AccountMaster to ensure all Trainees/Employees are in filter options
                all_master = session_obj.query(AccountMaster).all()
                for am in all_master:
                    if am.account_id:
                        account_map[am.account_id] = {
                            "account_id": am.account_id,
                            "account_name": am.account_name or am.account_id,
                            "cost": 0.0,
                        }

                for r in results:
                    acc_id = r[0]
                    acc_name = r[1] or acc_id
                    cost_val = float(r[2] or 0.0)
                    if acc_id not in account_map:
                        account_map[acc_id] = {
                            "account_id": acc_id,
                            "account_name": acc_name,
                            "cost": 0.0,
                        }
                    account_map[acc_id]["cost"] += cost_val
                    if acc_name and acc_name != acc_id:
                        account_map[acc_id]["account_name"] = acc_name

                total = sum(v["cost"] for v in account_map.values())
                sorted_accounts = sorted(account_map.values(), key=lambda x: x["cost"], reverse=True)
                return [
                    {
                        "account_id": item["account_id"],
                        "account_name": item["account_name"],
                        "cost": round(item["cost"], 4),
                        "percentage": round((item["cost"] / total) * 100, 1) if total else 0.0
                    }
                    for item in sorted_accounts
                ]
            else:
                total = sum(float(r[1]) for r in results)
                dim_str = dimension.value.lower()
                return [
                    {
                        dim_str: r[0] or "None",
                        "cost": round(float(r[1]), 4),
                        "percentage": round((float(r[1]) / total) * 100, 1) if total else 0.0
                    }
                    for r in results
                ]

    def get_dimension_trend(
        self,
        dimension: DimensionType,
        item: str,
        limit: int = 6,
        product: str | None = None,
        team: str | None = None,
        environment: str | None = None,
        account: str | None = None,
        region: str | None = None,
    ) -> list[dict[str, Any]]:
        session = self._get_session()
        if session is None:
            return []
        with session as session_obj:
            periods = [
                row[0]
                for row in session_obj.query(MonthlyCost.billing_period)
                .order_by(MonthlyCost.billing_period.desc())
                .limit(limit)
                .all()
            ]
            if not periods:
                return []
            
            periods = list(reversed(periods))

            if dimension == DimensionType.PRODUCT:
                col = ServiceCost.product
            elif dimension == DimensionType.TEAM:
                col = ServiceCost.team
            elif dimension == DimensionType.ENVIRONMENT:
                col = ServiceCost.environment
            elif dimension == DimensionType.REGION:
                col = ServiceCost.region
            elif dimension == DimensionType.ACCOUNT:
                col = ServiceCost.account_name
            else:
                raise ValueError(f"Invalid dimension: {dimension}")

            trend_data = []
            for p in periods:
                query = session_obj.query(func.sum(ServiceCost.cost))
                query = self._apply_filters(
                    query,
                    billing_period=p,
                    product=product,
                    team=team,
                    environment=environment,
                    account=account,
                    region=region
                )
                
                if dimension == DimensionType.PRODUCT:
                    query = query.filter(ServiceCost.product.in_(["SafeStart", "AccuTrain"]))
                elif dimension == DimensionType.ENVIRONMENT:
                    query = query.filter(ServiceCost.environment.in_(["QA", "UAT", "Production", "Development"]))

                if dimension == DimensionType.ACCOUNT:
                    query = query.filter((ServiceCost.account_name.ilike(item)) | (ServiceCost.account_id == item))
                else:
                    query = query.filter(col.ilike(item))

                val_query = query.scalar()
                val = float(val_query) if val_query is not None else 0.0
                trend_data.append({
                    "billing_period": p,
                    "cost": round(val, 4)
                })
            return trend_data

    def get_dimension_comparison(
        self,
        dimension: DimensionType,
        item_a: str,
        item_b: str,
        billing_period: str | None = None,
        product: str | None = None,
        team: str | None = None,
        environment: str | None = None,
        account: str | None = None,
        region: str | None = None,
    ) -> dict[str, Any] | None:
        session = self._get_session()
        if session is None:
            return None
        with session as session_obj:
            period = billing_period or self._latest_period(session_obj)
            if not period:
                return None
            
            if dimension == DimensionType.PRODUCT:
                col = ServiceCost.product
            elif dimension == DimensionType.TEAM:
                col = ServiceCost.team
            elif dimension == DimensionType.ENVIRONMENT:
                col = ServiceCost.environment
            elif dimension == DimensionType.REGION:
                col = ServiceCost.region
            elif dimension == DimensionType.ACCOUNT:
                col = ServiceCost.account_name
            else:
                raise ValueError(f"Invalid dimension: {dimension}")

            query_a = session_obj.query(func.sum(ServiceCost.cost))
            query_a = self._apply_filters(
                query_a,
                billing_period=period,
                product=product,
                team=team,
                environment=environment,
                account=account,
                region=region
            )
            if dimension == DimensionType.PRODUCT:
                query_a = query_a.filter(ServiceCost.product.in_(["SafeStart", "AccuTrain"]))
            elif dimension == DimensionType.ENVIRONMENT:
                query_a = query_a.filter(ServiceCost.environment.in_(["QA", "UAT", "Production", "Development"]))

            if dimension == DimensionType.ACCOUNT:
                query_a = query_a.filter((ServiceCost.account_name.ilike(item_a)) | (ServiceCost.account_id == item_a))
            else:
                query_a = query_a.filter(col.ilike(item_a))
            cost_a_query = query_a.scalar()

            query_b = session_obj.query(func.sum(ServiceCost.cost))
            query_b = self._apply_filters(
                query_b,
                billing_period=period,
                product=product,
                team=team,
                environment=environment,
                account=account,
                region=region
            )
            if dimension == DimensionType.PRODUCT:
                query_b = query_b.filter(ServiceCost.product.in_(["SafeStart", "AccuTrain"]))
            elif dimension == DimensionType.ENVIRONMENT:
                query_b = query_b.filter(ServiceCost.environment.in_(["QA", "UAT", "Production", "Development"]))

            if dimension == DimensionType.ACCOUNT:
                query_b = query_b.filter((ServiceCost.account_name.ilike(item_b)) | (ServiceCost.account_id == item_b))
            else:
                query_b = query_b.filter(col.ilike(item_b))
            cost_b_query = query_b.scalar()

            val_a = float(cost_a_query) if cost_a_query is not None else 0.0
            val_b = float(cost_b_query) if cost_b_query is not None else 0.0
            diff = round(val_a - val_b, 4)
            ratio = round(val_a / val_b, 2) if val_b else None

            dim_str = dimension.value.lower()
            return {
                "analysis": f"{dim_str}_comparison",
                "billing_period": period,
                "item_a": item_a,
                "item_b": item_b,
                "cost_a": val_a,
                "cost_b": val_b,
                "difference": diff,
                "ratio": ratio,
                "higher_item": item_a if diff >= 0 else item_b,
                "lower_item": item_b if diff >= 0 else item_a
            }

    def get_dimension_summary(
        self,
        dimension: DimensionType,
        billing_period: str | None = None,
        product: str | None = None,
        team: str | None = None,
        environment: str | None = None,
        account: str | None = None,
        region: str | None = None,
    ) -> dict[str, Any] | None:
        breakdown = self.get_dimension_breakdown(
            dimension=dimension,
            billing_period=billing_period,
            product=product,
            team=team,
            environment=environment,
            account=account,
            region=region
        )
        
        session = self._get_session()
        if session is None:
            return None
        with session as session_obj:
            period = billing_period or self._latest_period(session_obj)
            if not period:
                return None
            
            prev_period = self._previous_period(period)
            
            curr_sum_query = session_obj.query(func.sum(ServiceCost.cost))
            curr_sum_query = self._apply_filters(curr_sum_query, period, product, team, environment, account, region)
            curr_val = float(curr_sum_query.scalar() or 0.0)
            
            prev_sum_query = session_obj.query(func.sum(ServiceCost.cost))
            prev_sum_query = self._apply_filters(prev_sum_query, prev_period, product, team, environment, account, region)
            prev_val = float(prev_sum_query.scalar() or 0.0)
            
            diff = curr_val - prev_val
            pct = round((diff / prev_val) * 100, 1) if prev_val else 0.0
            
            return {
                "dimension": dimension.value.lower(),
                "billing_period": period,
                "total_cost": round(curr_val, 4),
                "previous_cost": round(prev_val, 4),
                "difference": round(diff, 4),
                "percentage_change": pct,
                "breakdown": breakdown
            }

    def get_developer_analysis(
        self,
        billing_period: str | None = None,
        product: str | None = None,
        environment: str | None = None,
        region: str | None = None,
        account: str | None = None,
    ) -> dict[str, Any] | None:
        session = self._get_session()
        if session is None:
            return None
        with session as session_obj:
            # Sync latest Account.csv mappings from S3 into account_master & service_costs
            try:
                from app.etl.account_loader import load_accounts
                load_accounts(session_obj)
            except Exception as sync_err:
                logger.warning(f"On-demand account master sync skipped: {sync_err}")

            period = billing_period or self._latest_period(session_obj)
            if not period:
                return None
            
            # Calculate total cost matching filters
            total_cost_query = session_obj.query(func.sum(ServiceCost.cost))
            total_cost_query = self._apply_filters(
                total_cost_query,
                billing_period=period,
                product=product,
                environment=environment,
                account=account,
                region=region
            )
            total_month = float(total_cost_query.scalar() or 0.0)

            # Resolve developer_type and account_name directly from AccountMaster as single source of truth
            effective_dev_type = func.coalesce(
                AccountMaster.developer_type,
                ServiceCost.developer_type
            )
            effective_acc_name = func.coalesce(AccountMaster.account_name, ServiceCost.account_name)

            dev_query = session_obj.query(
                ServiceCost.account_id,
                effective_acc_name.label("account_name"),
                effective_dev_type.label("developer_type"),
                ServiceCost.cost
            ).outerjoin(
                AccountMaster, ServiceCost.account_id == AccountMaster.account_id
            ).filter(
                ServiceCost.billing_period == period,
                (effective_dev_type.isnot(None)) | (AccountMaster.team == "Developers")
            )

            # Apply region and account filters (product/environment filters don't restrict developer accounts)
            if region:
                dev_query = dev_query.filter(ServiceCost.region == region)
            if account:
                dev_query = dev_query.filter((ServiceCost.account_name == account) | (ServiceCost.account_id == account))

            dev_rows = dev_query.all()

            account_costs: dict[str, dict[str, Any]] = {}

            # Pre-populate all accounts from AccountMaster under Developers team to ensure 0-cost accounts are displayed
            master_dev_accounts = session_obj.query(AccountMaster).filter(
                (AccountMaster.developer_type.in_(["Employee", "Trainee"])) |
                (AccountMaster.team == "Developers")
            ).all()

            for acc in master_dev_accounts:
                acc_key = acc.account_name or acc.account_id
                if acc_key:
                    dev_t = "Trainee" if (acc.developer_type and "trainee" in acc.developer_type.lower()) else "Employee"
                    account_costs[acc_key] = {"cost": 0.0, "developer_type": dev_t}

            employee_cost = 0.0
            trainee_cost = 0.0
            total_dev = 0.0

            for acc_id, acc_name, dev_type, cost in dev_rows:
                val = float(cost)
                total_dev += val
                norm_type = (dev_type or "").strip()
                if "trainee" in norm_type.lower():
                    trainee_cost += val
                    formatted_type = "Trainee"
                else:
                    employee_cost += val
                    formatted_type = "Employee"
                
                acc_key = acc_name or acc_id or "Unknown Account"
                if acc_key not in account_costs:
                    account_costs[acc_key] = {"cost": 0.0, "developer_type": formatted_type}
                account_costs[acc_key]["cost"] += val
                account_costs[acc_key]["developer_type"] = formatted_type

            breakdown = [
                {
                    "account": k,
                    "cost": round(v["cost"], 4),
                    "developer_type": v["developer_type"],
                    "percentage": round((v["cost"] / total_dev) * 100, 1) if total_dev else 0.0
                }
                for k, v in sorted(account_costs.items(), key=lambda x: x[1]["cost"], reverse=True)
            ]

            return {
                "analysis": "developer_analysis",
                "billing_period": period,
                "total_developer_cost": round(total_dev, 4),
                "total_month_cost": total_month,
                "developer_percentage": round((total_dev / total_month) * 100, 1) if total_month else 0.0,
                "employee_cost": round(employee_cost, 4),
                "employee_percentage": round((employee_cost / total_dev) * 100, 1) if total_dev else 0.0,
                "trainee_cost": round(trainee_cost, 4),
                "trainee_percentage": round((trainee_cost / total_dev) * 100, 1) if total_dev else 0.0,
                "breakdown": breakdown
            }

    def get_shared_infrastructure_analysis(
        self,
        billing_period: str | None = None,
        product: str | None = None,
        environment: str | None = None,
        region: str | None = None,
        account: str | None = None,
    ) -> dict[str, Any] | None:
        session = self._get_session()
        if session is None:
            return None
        with session as session_obj:
            period = billing_period or self._latest_period(session_obj)
            if not period:
                return None
            
            # Calculate total cost matching filters
            total_cost_query = session_obj.query(func.sum(ServiceCost.cost))
            total_cost_query = self._apply_filters(
                total_cost_query,
                billing_period=period,
                product=product,
                environment=environment,
                account=account,
                region=region
            )
            total_month = float(total_cost_query.scalar() or 0.0)

            shared_query = session_obj.query(
                ServiceCost.team,
                ServiceCost.environment,
                ServiceCost.cost
            ).filter(
                ServiceCost.billing_period == period,
                (ServiceCost.product.is_(None)) | (ServiceCost.product == "") |
                (ServiceCost.environment.in_(["Sandbox", "Audit", "Logs", "Data Platform"])) |
                (ServiceCost.team.in_(["Sandbox", "Audit", "Logs", "Data Platform"]))
            )
            shared_query = self._apply_filters(
                shared_query,
                product=product,
                environment=environment,
                account=account,
                region=region
            )
            shared_rows = shared_query.all()

            categories = {
                "Sandbox": 0.0,
                "Audit": 0.0,
                "Logs": 0.0,
                "Data Platform": 0.0,
                "Other Shared": 0.0
            }
            total_shared = 0.0
            for team, env, cost in shared_rows:
                val = float(cost)
                total_shared += val
                matched = False
                for cat in ["Sandbox", "Audit", "Logs", "Data Platform"]:
                    if team == cat or env == cat:
                        categories[cat] += val
                        matched = True
                        break
                if not matched:
                    categories["Other Shared"] += val

            breakdown = [
                {
                    "component": k,
                    "cost": round(v, 4),
                    "percentage": round((v / total_month) * 100, 1) if total_month else 0.0
                }
                for k, v in categories.items() if v > 0
            ]

            return {
                "analysis": "shared_infrastructure",
                "billing_period": period,
                "total_shared_cost": round(total_shared, 4),
                "total_month_cost": total_month,
                "shared_percentage": round((total_shared / total_month) * 100, 1) if total_month else 0.0,
                "breakdown": breakdown
            }

    def get_top_services_for_product(
        self,
        product: str,
        billing_period: str | None = None,
        limit: int = 5,
    ) -> dict[str, Any] | None:
        """Query service_costs table for top AWS services contributing to a specific product."""
        session = self._get_session()
        if not session:
            return None
        with session as session_obj:
            from sqlalchemy import func
            query = session_obj.query(
                ServiceCost.raw_service_name.label("service"),
                func.sum(ServiceCost.cost).label("total_cost"),
            ).filter(ServiceCost.product.ilike(f"%{product.strip()}%"))

            if billing_period:
                query = query.filter(ServiceCost.billing_period == billing_period.strip())

            rows = (
                query.group_by(ServiceCost.raw_service_name)
                .order_by(func.sum(ServiceCost.cost).desc())
                .limit(limit)
                .all()
            )

            if not rows:
                return None

            total = sum(self._to_float(r.total_cost) or 0.0 for r in rows)
            services = [
                {
                    "service": r.service or "Other Services",
                    "cost": round(self._to_float(r.total_cost) or 0.0, 4),
                    "percentage": round(((self._to_float(r.total_cost) or 0.0) / total) * 100, 1) if total else 0.0,
                }
                for r in rows
            ]

            logger.info(
                "[EXECUTE REPO] Function: get_top_services_for_product | Params: product='%s', period='%s' | Returned Rows: %d | Breakdown: %s",
                product, billing_period, len(rows), services
            )

            return {
                "analysis": "product_services_breakdown",
                "product": product,
                "billing_period": billing_period,
                "total_cost": round(total, 4),
                "top_services": services,
                "services": services,
            }

    def get_product_breakdown_for_service(
        self,
        service_name: str,
        billing_period: str | None = None,
    ) -> dict[str, Any] | None:
        """Query service_costs table for product breakdown using a specific AWS service."""
        session = self._get_session()
        if not session:
            return None
        with session as session_obj:
            from sqlalchemy import func, or_
            svc_pattern = f"%{service_name.strip()}%"
            query = session_obj.query(
                ServiceCost.product.label("product"),
                func.sum(ServiceCost.cost).label("total_cost"),
            ).filter(
                or_(
                    ServiceCost.raw_service_name.ilike(svc_pattern),
                    ServiceCost.business_service_name.ilike(svc_pattern),
                )
            )

            if billing_period:
                query = query.filter(ServiceCost.billing_period == billing_period.strip())

            rows = (
                query.group_by(ServiceCost.product)
                .order_by(func.sum(ServiceCost.cost).desc())
                .all()
            )

            if not rows:
                logger.warning(
                    "[EXECUTE REPO] Function: get_product_breakdown_for_service | Params: pattern='%s', period='%s' | Returned 0 rows",
                    svc_pattern, billing_period
                )
                return None

            total = sum(self._to_float(r.total_cost) or 0.0 for r in rows)
            products = [
                {
                    "product": r.product or "Unassigned Product",
                    "cost": round(self._to_float(r.total_cost) or 0.0, 4),
                    "percentage": round(((self._to_float(r.total_cost) or 0.0) / total) * 100, 1) if total else 0.0,
                }
                for r in rows
            ]

            logger.info(
                "[EXECUTE REPO] Function: get_product_breakdown_for_service | Params: pattern='%s', period='%s' | Returned Rows: %d | Breakdown: %s",
                svc_pattern, billing_period, len(rows), products
            )

            return {
                "analysis": "service_products_breakdown",
                "service": service_name,
                "billing_period": billing_period,
                "total_cost": round(total, 4),
                "products": products,
                "breakdown": products,
            }
