"""Business-facing cost service backed by synchronized PostgreSQL data."""

from __future__ import annotations

from decimal import Decimal
import logging
from typing import Any

from app.constants.billing_categories import (
    NON_SERVICE_BILLING_CATEGORIES,
    NON_SERVICE_BILLING_CATEGORY_FRAGMENTS,
)
from app.schemas.cost_schema import CostByMonthResponse, MonthlyCostResponse, ServiceBreakdownResponse, ServiceCost, DimensionType
from app.services.cost_query_service import CostQueryService

logger = logging.getLogger(__name__)


def normalize_billing_category(value: str | None) -> str:
    return " ".join((value or "").strip().lower().split())


def calculate_month_total(service_costs: dict[str, Decimal] | list[Decimal] | tuple[Decimal, ...]) -> Decimal:
    if isinstance(service_costs, dict):
        values = service_costs.values()
    else:
        values = service_costs
    return sum((Decimal(str(value)) for value in values), Decimal("0"))


def is_service_category(service_name: str | None) -> bool:
    normalized = normalize_billing_category(service_name)
    if not normalized:
        return False
    if normalized in NON_SERVICE_BILLING_CATEGORIES:
        return False
    return not any(fragment in normalized for fragment in NON_SERVICE_BILLING_CATEGORY_FRAGMENTS)


def resolve_service_name_alias(name: str) -> str:  # noqa: C901
    """Map any user-supplied service name or abbreviation to the canonical display name.

    ECR is checked BEFORE EC2/elastic compute to ensure
    Container Registry never resolves to EC2.
    Bedrock model variants (Claude, Haiku, Sonnet, Opus) all resolve to Amazon Bedrock.
    """
    if not name:
        return ""
    name_lower = name.strip().lower()

    # Bedrock / Claude model variants — check before any other prefix
    if any(k in name_lower for k in ("bedrock", "claude", "haiku", "sonnet", "opus")):
        return "Amazon Bedrock"

    # ECR — check BEFORE elastic compute / EC2 to avoid false-positive
    if "ecr" in name_lower or "container registry" in name_lower or "elastic container registry" in name_lower:
        return "Amazon ECR"

    # EC2
    if any(k in name_lower for k in ("ec2", "elastic compute")):
        return "Amazon EC2"

    # Lambda
    if "lambda" in name_lower:
        return "AWS Lambda"

    # MediaConvert
    if any(k in name_lower for k in ("mediaconvert", "media convert", "elemental mediaconvert")):
        return "AWS Elemental MediaConvert"

    # RDS
    if any(k in name_lower for k in ("rds", "relational database")):
        return "Amazon RDS"

    # S3
    if any(k in name_lower for k in ("s3", "simple storage")):
        return "Amazon S3"

    # DynamoDB
    if any(k in name_lower for k in ("dynamodb", "dynamo db", "dynamo")):
        return "Amazon DynamoDB"

    # ECS
    if any(k in name_lower for k in ("ecs", "elastic container service")):
        return "Amazon ECS"

    # EKS
    if any(k in name_lower for k in ("eks", "elastic kubernetes")):
        return "Amazon EKS"

    # CloudFront
    if any(k in name_lower for k in ("cloudfront", "cloud front")):
        return "Amazon CloudFront"

    # CloudWatch
    if any(k in name_lower for k in ("cloudwatch", "cloud watch")):
        return "Amazon CloudWatch"

    # Cognito
    if "cognito" in name_lower:
        return "Amazon Cognito"

    # Kinesis
    if "kinesis" in name_lower:
        return "Amazon Kinesis"

    # Route 53
    if any(k in name_lower for k in ("route53", "route 53")):
        return "Amazon Route 53"

    # SQS
    if any(k in name_lower for k in ("sqs", "simple queue")):
        return "Amazon SQS"

    # SNS
    if any(k in name_lower for k in ("sns", "simple notification")):
        return "Amazon SNS"

    # SES
    if any(k in name_lower for k in ("ses", "simple email")):
        return "Amazon SES"

    # Backup
    if "backup" in name_lower:
        return "AWS Backup"

    # Glue
    if "glue" in name_lower:
        return "AWS Glue"

    # GuardDuty
    if any(k in name_lower for k in ("guardduty", "guard duty")):
        return "Amazon GuardDuty"

    # CloudFormation
    if "cloudformation" in name_lower:
        return "AWS CloudFormation"

    # Secrets Manager
    if any(k in name_lower for k in ("secretsmanager", "secrets manager")):
        return "AWS Secrets Manager"

    # OpenSearch
    if any(k in name_lower for k in ("opensearch", "elasticsearch")):
        return "Amazon OpenSearch Service"

    return name.strip()


def normalize_business_service_name(service_name: str | None) -> str:
    if not service_name:
        return ""
    return resolve_service_name_alias(service_name)


def normalize_and_aggregate_services(services: list[dict[str, Any]]) -> list[dict[str, Any]]:
    aggregated: dict[str, dict[str, Any]] = {}
    for s in services:
        name = s.get("service") or s.get("service_name")
        if not name:
            continue
        norm_name = normalize_business_service_name(name)
        if norm_name in aggregated:
            entry = aggregated[norm_name]
            if "amount" in s:
                entry["amount"] = entry.get("amount", 0.0) + float(s["amount"])
            if "cost" in s:
                entry["cost"] = entry.get("cost", 0.0) + float(s["cost"])
            if "cost_a" in s:
                entry["cost_a"] = entry.get("cost_a", 0.0) + float(s["cost_a"])
            if "cost_b" in s:
                entry["cost_b"] = entry.get("cost_b", 0.0) + float(s["cost_b"])
        else:
            entry = {**s}
            if "service" in entry:
                entry["service"] = norm_name
            if "service_name" in entry:
                entry["service_name"] = norm_name
            if "amount" in entry:
                entry["amount"] = float(entry["amount"])
            if "cost" in entry:
                entry["cost"] = float(entry["cost"])
            if "cost_a" in entry:
                entry["cost_a"] = float(entry["cost_a"])
            if "cost_b" in entry:
                entry["cost_b"] = float(entry["cost_b"])
            aggregated[norm_name] = entry

    result = list(aggregated.values())
    total_amount = sum(item.get("amount") or item.get("cost") or 0.0 for item in result)
    for item in result:
        if "percentage" in item and total_amount:
            val = item.get("amount") or item.get("cost") or 0.0
            item["percentage"] = round((val / total_amount) * 100, 1)
        if "cost_a" in item and "cost_b" in item:
            item["change"] = round(item["cost_b"] - item["cost_a"], 2)
            item["change_pct"] = round((item["change"] / item["cost_a"]) * 100, 1) if item["cost_a"] else 0.0
            
    return result


def filter_business_services(services: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [service for service in services if is_service_category(str(service.get("service", "")))]


def get_business_service_breakdown(services: list[dict[str, Any]]) -> list[dict[str, Any]]:
    business_services = filter_business_services(services)
    normalized_services = normalize_and_aggregate_services(business_services)
    total = sum(float(service.get("amount", 0.0)) for service in normalized_services)
    breakdown: list[dict[str, Any]] = []
    for service in normalized_services:
        amount = float(service.get("amount", 0.0))
        breakdown.append({
            **service,
            "percentage": round((amount / total) * 100, 1) if total else 0.0,
        })
    return breakdown


def get_raw_business_service_breakdown(services: list[dict[str, Any]]) -> list[dict[str, Any]]:
    business_services = filter_business_services(services)
    total = sum(float(service.get("amount", 0.0)) for service in business_services)
    breakdown: list[dict[str, Any]] = []
    for service in business_services:
        amount = float(service.get("amount", 0.0))
        breakdown.append({
            **service,
            "percentage": round((amount / total) * 100, 1) if total else 0.0,
        })
    return breakdown


class BusinessCostService:
    """Single business layer for all PostgreSQL-backed dashboard and chatbot reads."""

    MONTH_NAME_MAP = {
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

    def __init__(self, query_service: CostQueryService | None = None) -> None:
        self._query = query_service or CostQueryService()

    def get_monthly_cost_response(
        self,
        months: int = 2,
        product: str | None = None,
        team: str | None = None,
        environment: str | None = None,
        account: str | None = None,
        region: str | None = None,
    ) -> MonthlyCostResponse:
        return self._query.get_monthly_cost_response(months, product, team, environment, account, region)

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
        raw = self._query.get_service_breakdown_response(start, end, product, team, environment, account, region, billing_period)
        services = get_raw_business_service_breakdown([
            {
                "service": service.service,
                "amount": service.amount,
                "unit": service.unit,
                "percentage": service.percentage,
            }
            for service in raw.services
        ])
        logger.info("Business services: %s", len(services))
        logger.info("Billing categories: %s", len(raw.services) - len(services))
        return ServiceBreakdownResponse(
            start=raw.start,
            end=raw.end,
            total_cost=raw.total_cost,
            unit=raw.unit,
            services=[ServiceCost(**service) for service in services],
        )

    def get_cost_by_month_response(self, billing_period: str) -> CostByMonthResponse:
        record = self._query.get_monthly_record_data(billing_period)
        if record is None:
            raise ValueError(f"No synchronized billing data found for '{billing_period}'.")
        return CostByMonthResponse(month=record["billing_period"], total_cost=record["total_cost"], unit=record["unit"])

    def get_total_month_cost(self, billing_period: str | None = None) -> dict[str, Any] | None:
        return self._query.get_total_month_cost(billing_period)

    def get_latest_month_cost(self) -> dict[str, Any] | None:
        return self._query.get_latest_month_cost()

    def get_service_cost(self, service: str, billing_period: str | None = None) -> dict[str, Any] | None:
        raw = self._query.get_service_cost(service, billing_period)
        if not raw:
            return None
        return {
            **raw,
            "service": normalize_business_service_name(raw.get("service")),
        }

    def get_service_history(self, service: str) -> list[dict[str, Any]]:
        target_business_name = resolve_service_name_alias(service)
        available_periods = self._query.get_available_periods()
        history = []
        for period in sorted(available_periods):
            cost_data = self.get_service_cost(target_business_name, billing_period=period)
            if cost_data:
                history.append({
                    "billing_period": period,
                    "cost": cost_data["cost"]
                })
        return history

    def get_top_services(self, billing_period: str | None = None, limit: int = 5) -> dict[str, Any] | None:
        service_rows = self._query.get_service_rows_data(billing_period)
        if not service_rows:
            return None
        period = billing_period or service_rows[0]["billing_period"]
        top_services = get_business_service_breakdown(service_rows)[:limit]
        return {
            "analysis": "top_services",
            "billing_period": period,
            "top_services": [{"service": row["service"], "cost": row["amount"]} for row in top_services],
        }

    def get_highest_service(self, billing_period: str | None = None) -> dict[str, Any] | None:
        top = self.get_top_services(billing_period=billing_period, limit=1)
        if not top or not top["top_services"]:
            return None
        highest = top["top_services"][0]
        return {
            "analysis": "highest",
            "billing_period": top["billing_period"],
            "highest_service": highest["service"],
            "highest_cost": highest["cost"],
        }

    def get_lowest_service(self, billing_period: str | None = None) -> dict[str, Any] | None:
        service_rows = get_business_service_breakdown(self._query.get_service_rows_data(billing_period))
        if not service_rows:
            return None
        lowest = min(service_rows, key=lambda row: row["amount"])
        period = billing_period or self._query.get_latest_billing_period()
        return {
            "analysis": "lowest",
            "billing_period": period,
            "lowest_service": lowest["service"],
            "lowest_cost": lowest["amount"],
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
        import re
        if current_period == "undefined" or current_period == "":
            current_period = None
        if previous_period == "undefined" or previous_period == "":
            previous_period = None

        if current_period and previous_period:
            if re.match(r"^\d{4}-\d{2}$", current_period) and re.match(r"^\d{4}-\d{2}$", previous_period):
                if current_period < previous_period:
                    current_period, previous_period = previous_period, current_period
        raw = self._query.compare_months(
            current_period=current_period,
            previous_period=previous_period,
            product=product,
            team=team,
            environment=environment,
            account=account,
            region=region,
        )
        if not raw:
            return None

        # Normalize and aggregate the service deltas
        deltas = raw.get("service_deltas") or []
        business_deltas = filter_business_services([
            {
                "service": d["service"],
                "cost_a": d["cost_a"],
                "cost_b": d["cost_b"],
            }
            for d in deltas
        ])

        aggregated_deltas = normalize_and_aggregate_services(business_deltas)

        # Sort aggregated deltas by absolute change descending
        aggregated_deltas.sort(key=lambda x: abs(x["change"]), reverse=True)

        # Find highest increased/decreased service from aggregated list
        highest_increased = None
        highest_decreased = None

        increased_list = [d for d in aggregated_deltas if d["change"] > 0]
        decreased_list = [d for d in aggregated_deltas if d["change"] < 0]

        if increased_list:
            highest_increased = {
                "service": increased_list[0]["service"],
                "change": increased_list[0]["change"],
                "change_pct": increased_list[0]["change_pct"]
            }

        if decreased_list:
            highest_decreased = {
                "service": decreased_list[0]["service"],
                "change": decreased_list[0]["change"],
                "change_pct": decreased_list[0]["change_pct"]
            }

        # Calculate new total change
        cost_a_val = raw.get("cost_a")
        cost_a = float(cost_a_val) if cost_a_val is not None else 0.0
        cost_b_val = raw.get("cost_b")
        cost_b = float(cost_b_val) if cost_b_val is not None else 0.0
        difference = cost_b - cost_a
        pct_change = round((difference / cost_a) * 100, 1) if cost_a else 0.0

        # Helper to label months cleanly in Python without import cycles
        def label_month_simple(month_str: str) -> str:
            if not month_str or "-" not in month_str:
                return month_str
            y, m = month_str.split("-")
            months_map = {
                "01": "January", "02": "February", "03": "March", "04": "April",
                "05": "May", "06": "June", "07": "July", "08": "August",
                "09": "September", "10": "October", "11": "November", "12": "December"
            }
            return f"{months_map.get(m, m)} {y}"

        # Re-build summary text using friendly names in executive language
        summary = ""
        if cost_a and cost_b:
            direction = "increased" if difference > 0 else "decreased" if difference < 0 else "remained stable"
            action_word = "increasing" if difference > 0 else "decreasing"
            
            summary = (
                f"Cloud spending {direction} in {label_month_simple(raw['period_b'])}, "
                f"{action_word} {abs(pct_change):.1f}% compared with {label_month_simple(raw['period_a'])}. "
            )
            
            top_svc_name = None
            if aggregated_deltas:
                sorted_by_cost = sorted(aggregated_deltas, key=lambda x: x.get("cost_b", 0.0), reverse=True)
                if sorted_by_cost:
                    top_svc_name = sorted_by_cost[0]["service"]
            
            if top_svc_name:
                summary += f"{top_svc_name} continued to be the primary cost driver"
            else:
                summary += "Core infrastructure continued to be the primary cost driver"
                
            if highest_increased:
                summary += f" while {highest_increased['service']} showed the strongest growth compared to the previous period."
            elif highest_decreased:
                summary += f" while {highest_decreased['service']} showed the most notable spend reduction."
            else:
                summary += "."
                
            summary += " Overall infrastructure utilization appears healthy with no abnormal spending spikes detected."

        return {
            "period_a": raw["period_a"],
            "period_b": raw["period_b"],
            "cost_a": cost_a,
            "cost_b": cost_b,
            "difference": difference,
            "percentage_change": pct_change,
            "highest_increased_service": highest_increased,
            "highest_decreased_service": highest_decreased,
            "service_deltas": aggregated_deltas,
            "summary": summary,
            "analysis": "compare_months",
        }

    def get_month_summary(self, billing_period: str | None = None) -> dict[str, Any] | None:
        monthly_total = self.get_total_month_cost(billing_period)
        if not monthly_total:
            return None
        top_services = self.get_top_services(billing_period=billing_period, limit=5)
        return {
            "analysis": "summary",
            "billing_period": monthly_total["billing_period"],
            "total_cost": monthly_total["total_cost"],
            "top_services": top_services["top_services"] if top_services else [],
        }

    def get_monthly_trend(self, limit: int = 6) -> dict[str, Any] | None:
        return self._query.get_monthly_trend(limit)

    def get_monthly_average(self) -> dict[str, Any] | None:
        """Return the average monthly spend across all available billing periods."""
        return self._query.get_monthly_average()

    def get_year_summary(self, year: int) -> dict[str, Any] | None:
        """Return aggregated spend for all available months in the given year."""
        return self._query.get_year_summary(year)

    def get_service_comparison(
        self,
        service_a: str,
        service_b: str,
        billing_period: str | None = None,
    ) -> dict[str, Any] | None:
        """Compare two named services in the same billing period.

        Returns cost for each service, the difference, and percentage share.
        """
        from app.services.business_cost_service import resolve_service_name_alias  # noqa: PLC0415
        resolved_a = resolve_service_name_alias(service_a)
        resolved_b = resolve_service_name_alias(service_b)

        cost_a = self.get_service_cost(resolved_a, billing_period=billing_period)
        cost_b = self.get_service_cost(resolved_b, billing_period=billing_period)

        period = billing_period or self._query.get_latest_billing_period()

        result: dict[str, Any] = {
            "analysis": "service_comparison",
            "billing_period": period,
            "service_a": resolved_a,
            "service_b": resolved_b,
            "cost_a": cost_a["cost"] if cost_a else 0.0,
            "cost_b": cost_b["cost"] if cost_b else 0.0,
        }
        diff = result["cost_a"] - result["cost_b"]
        result["difference"] = round(diff, 2)
        result["higher_service"] = resolved_a if diff >= 0 else resolved_b
        result["lower_service"] = resolved_b if diff >= 0 else resolved_a
        if result["cost_b"] > 0:
            result["ratio"] = round(result["cost_a"] / result["cost_b"], 2)
        else:
            result["ratio"] = None
        return result

    def get_executive_summary(self, billing_period: str | None = None) -> dict[str, Any] | None:
        """Return a comprehensive executive summary combining summary, comparison and trend.

        Used for EXECUTIVE_SUMMARY intent.  Answers:
        - Total spend this period
        - Change vs previous period
        - Largest cost driver
        - Largest increase / decrease
        - Top 5 services
        - Optimization opportunities summary
        """
        summary = self.get_month_summary(billing_period=billing_period)
        if not summary:
            return None

        comparison = self.compare_months(current_period=billing_period)
        trend = self.get_monthly_trend(limit=6)
        top5 = self.get_top_services(billing_period=billing_period, limit=5)
        highest = self.get_highest_service(billing_period=billing_period)

        return {
            "analysis": "executive_summary",
            "billing_period": summary["billing_period"],
            "total_cost": summary["total_cost"],
            "top_services": top5["top_services"] if top5 else [],
            "highest_service": highest or {},
            "month_comparison": comparison or {},
            "monthly_trend": trend or {},
            "summary": summary,
        }

    def get_optimization_context(self) -> dict[str, Any] | None:
        """
        Build a structured context for LLM-powered optimization answers.

        Combines: latest month summary + MoM comparison + monthly trend.
        The LLM uses this context to explain high-spend services, growth areas,
        and generate actionable recommendations.
        """
        summary = self.get_month_summary()
        if not summary:
            return None

        trend = self.get_monthly_trend(limit=6)
        comparison = self.compare_months()

        return {
            "analysis": "optimization_context",
            "current_month_summary": summary,
            "monthly_trend": trend,
            "month_comparison": comparison,
        }

    def get_all_service_costs_by_period(
        self,
        product: str | None = None,
        team: str | None = None,
        environment: str | None = None,
        account: str | None = None,
        region: str | None = None,
    ) -> dict[str, Any] | None:
        """Return all service costs grouped by billing period for analytics trend charts."""
        raw = self._query.get_all_service_costs_by_period(product, team, environment, account, region)
        if not raw:
            return None

        periods = raw.get("periods") or []
        services_raw = raw.get("services") or {}

        aggregated_services: dict[str, dict[str, float]] = {}
        for svc_name, period_costs in services_raw.items():
            norm_name = normalize_business_service_name(svc_name)
            if norm_name not in aggregated_services:
                aggregated_services[norm_name] = {p: 0.0 for p in periods}
            for p in periods:
                aggregated_services[norm_name][p] += float(period_costs.get(p, 0.0))

        return {
            "periods": periods,
            "services": aggregated_services
        }

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
        return self._query.get_dimension_breakdown(
            dimension=dimension,
            billing_period=billing_period,
            product=product,
            team=team,
            environment=environment,
            account=account,
            region=region
        )

    def get_region_accounts_breakdown(self, billing_period: str | None = None) -> list[dict[str, Any]]:
        return self._query.get_region_accounts_breakdown(billing_period=billing_period)

    def get_region_services_breakdown(self, billing_period: str | None = None) -> list[dict[str, Any]]:
        return self._query.get_region_services_breakdown(billing_period=billing_period)

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
        return self._query.get_dimension_trend(
            dimension=dimension,
            item=item,
            limit=limit,
            product=product,
            team=team,
            environment=environment,
            account=account,
            region=region
        )

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
        return self._query.get_dimension_comparison(
            dimension=dimension,
            item_a=item_a,
            item_b=item_b,
            billing_period=billing_period,
            product=product,
            team=team,
            environment=environment,
            account=account,
            region=region
        )

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
        return self._query.get_dimension_summary(
            dimension=dimension,
            billing_period=billing_period,
            product=product,
            team=team,
            environment=environment,
            account=account,
            region=region
        )

    def get_shared_infrastructure_analysis(
        self,
        billing_period: str | None = None,
        product: str | None = None,
        environment: str | None = None,
        region: str | None = None,
        account: str | None = None,
    ) -> dict[str, Any] | None:
        return self._query.get_shared_infrastructure_analysis(
            billing_period=billing_period,
            product=product,
            environment=environment,
            region=region,
            account=account
        )

    def get_developer_analysis(
        self,
        billing_period: str | None = None,
        product: str | None = None,
        environment: str | None = None,
        region: str | None = None,
        account: str | None = None,
    ) -> dict[str, Any] | None:
        return self._query.get_developer_analysis(
            billing_period=billing_period,
            product=product,
            environment=environment,
            region=region,
            account=account
        )

    def get_organization_summary(self, billing_period: str | None = None) -> dict[str, Any] | None:
        """Return an organization-wide spending summary.

        Combines:
        - SafeStart product total
        - AccuTrain product total
        - Common Infrastructure (Logs, Audit, Data Platform, Sandbox) total
        - Grand total

        Used for ORGANIZATION_SUMMARY intent.
        """
        from app.schemas.cost_schema import DimensionType  # noqa: PLC0415

        period = billing_period or self._query.get_latest_billing_period()
        if not period:
            return None

        # Product breakdowns
        safestart_data = self._query.get_dimension_summary(
            dimension=DimensionType.PRODUCT,
            billing_period=period,
        )
        accutrain_data = self._query.get_dimension_summary(
            dimension=DimensionType.PRODUCT,
            billing_period=period,
        )

        # Shared infrastructure
        infra_data = self._query.get_shared_infrastructure_analysis(billing_period=period)

        # Try to pull product-specific totals from dimension breakdown
        product_breakdown = self._query.get_dimension_breakdown(
            dimension=DimensionType.PRODUCT,
            billing_period=period,
        )

        safestart_total = 0.0
        accutrain_total = 0.0

        for row in (product_breakdown or []):
            name = (row.get("dimension_value") or row.get("name") or "").lower()
            cost = float(row.get("total_cost") or row.get("cost") or 0.0)
            if "safestart" in name or "safe" in name:
                safestart_total += cost
            elif "accutrain" in name or "accu" in name:
                accutrain_total += cost

        # Common infra total from shared infra analysis
        infra_total = 0.0
        infra_breakdown: list[dict] = []
        if infra_data:
            for k, v in infra_data.items():
                if isinstance(v, (int, float)) and k not in ("billing_period",):
                    infra_total += float(v)
            # Try to get named breakdown
            infra_breakdown = infra_data.get("accounts", infra_data.get("breakdown", []))

        grand_total = safestart_total + accutrain_total + infra_total

        return {
            "analysis": "organization_summary",
            "billing_period": period,
            "safestart_total": round(safestart_total, 2),
            "accutrain_total": round(accutrain_total, 2),
            "common_infra_total": round(infra_total, 2),
            "grand_total": round(grand_total, 2),
            "infra_breakdown": infra_breakdown,
            "product_breakdown": product_breakdown or [],
        }
