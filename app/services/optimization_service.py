"""PostgreSQL-backed Cost Optimization Service.

Generates data-driven recommendations from historical billing data.
Never hallucinate — all recommendations are derived from actual MonthlyCost
and ServiceCost records.
"""

from __future__ import annotations

import logging
from typing import Any

from app.schemas.optimization_schema import (
    OptimizationRecommendation,
    OptimizationRecommendationResponse,
    OptimizationSummary,
)
from app.services.business_cost_service import (
    BusinessCostService,
    filter_business_services,
)
from app.services.cost_query_service import CostQueryService
from app.schemas.cost_schema import DimensionType

logger = logging.getLogger(__name__)

# Thresholds for classification
_HIGH_GROWTH_THRESHOLD_PCT = 30.0   # ≥30% MoM increase → HIGH priority
_SPIKE_THRESHOLD_PCT = 50.0          # ≥50% MoM increase → spike flag
_IDLE_COST_MAX = 1.0                  # ≤$1 services flagged as potentially idle
_TOP_SPEND_LIMIT = 5                  # Top N services by absolute cost
_SAVINGS_RATE = 0.15                  # Estimated 15% savings potential for flagged services


class OptimizationService:
    """
    Generate cost optimization recommendations from PostgreSQL billing data.

    All logic is deterministic and data-driven — no LLM involved in this service.
    The LLM (OpenRouterService) consumes the recommendations as structured context.
    """

    def __init__(self, query_service: CostQueryService | None = None) -> None:
        self._query = query_service or CostQueryService()
        self._business = BusinessCostService(query_service=self._query)

    def generate_recommendations(
        self,
        product: str | None = None,
        team: str | None = None,
        environment: str | None = None,
        account: str | None = None,
        region: str | None = None,
        billing_period: str | None = None,
    ) -> OptimizationRecommendationResponse:
        """Generate all optimization recommendations from PostgreSQL data."""
        available_periods = self._query.get_available_periods()
        if not available_periods:
            return self._empty_response()

        current_period = billing_period or available_periods[0]
        previous_period = CostQueryService._previous_period(current_period) if current_period else None

        # Get current period service data (business-filtered: no taxes, credits, etc.)
        current_rows = self._get_business_service_rows(current_period, product, team, environment, account, region)
        previous_rows = self._get_business_service_rows(previous_period, product, team, environment, account, region) if previous_period else []

        if not current_rows:
            return self._empty_response()

        previous_cost_map = {row["service"]: row["amount"] for row in previous_rows}
        current_total = sum(row["amount"] for row in current_rows)
        previous_total = sum(row["amount"] for row in previous_rows)

        recommendations: list[OptimizationRecommendation] = []

        # Collect all flagged services to avoid duplicates
        flagged_services: set[str] = set()

        # 1. High-growth services (large MoM increases)
        growth_recs = self._identify_high_growth(
            current_rows, previous_cost_map, current_total, flagged_services
        )
        recommendations.extend(growth_recs)

        # 2. Top spenders (absolute cost leaders)
        top_recs = self._identify_top_spenders(
            current_rows, previous_cost_map, current_total, flagged_services
        )
        recommendations.extend(top_recs)

        # 3. Idle / near-zero services
        idle_recs = self._identify_idle_services(current_rows, flagged_services)
        recommendations.extend(idle_recs)

        # 4. Dimension-level recommendations (Product, Team, Environment, Region, Account)
        for dim in [DimensionType.PRODUCT, DimensionType.TEAM, DimensionType.ENVIRONMENT, DimensionType.REGION, DimensionType.ACCOUNT]:
            dim_rows = self._business.get_dimension_breakdown(dim, current_period, product, team, environment, account, region)
            dim_prev = self._business.get_dimension_breakdown(dim, previous_period, product, team, environment, account, region) if previous_period else []
            prev_map = {}
            for r in dim_prev:
                val_key = r.get(dim.value.lower()) or r.get("account_name")
                if val_key:
                    prev_map[val_key] = r["cost"]

            # Limit top items to prevent recommendation bloat
            for item_row in dim_rows[:3]:
                name = item_row.get(dim.value.lower()) or item_row.get("account_name") or item_row.get("account_id")
                if not name or name == "None" or name == "Unknown":
                    continue

                cost_now = item_row["cost"]
                cost_prev = prev_map.get(name, 0.0)

                # High growth checklist
                change_pct = 0.0
                if cost_prev > 0:
                    change_pct = ((cost_now - cost_prev) / cost_prev) * 100

                flagged_dim = False
                priority = "LOW"
                issue = ""
                reason = ""
                savings = round(cost_now * _SAVINGS_RATE, 2)

                if change_pct >= _HIGH_GROWTH_THRESHOLD_PCT:
                    flagged_dim = True
                    priority = "HIGH" if change_pct >= _SPIKE_THRESHOLD_PCT else "MEDIUM"
                    issue = f"High growth in {dim.value.lower()}: {name}"
                    reason = f"{dim.value.title()} '{name}' spend grew from ${cost_prev:,.2f} to ${cost_now:,.2f} (+{change_pct:.1f}%) MoM."
                elif cost_now > (current_total * 0.15): # Represents > 15% of total spend
                    flagged_dim = True
                    priority = "MEDIUM"
                    issue = f"Significant spend category: {name}"
                    reason = f"{dim.value.title()} '{name}' represents a substantial {item_row['percentage']}% of your total cloud spend."

                if flagged_dim:
                    action = self._get_dimension_action(dim.value.lower(), name)
                    recommendations.append(OptimizationRecommendation(
                        service=f"{dim.value.title()}: {name}",
                        issue=issue,
                        reason=reason,
                        business_impact=f"This category represents ${cost_now:,.2f}/month. Optimizing it can significantly reduce overall spend.",
                        estimated_savings=f"${savings:,.2f}/month",
                        recommended_action=action,
                        priority=priority,
                        current_cost=round(cost_now, 2),
                        previous_cost=round(cost_prev, 2) if cost_prev else None,
                        change_pct=round(change_pct, 1) if cost_prev else None,
                        dimension=dim.value.lower(),
                        dimension_value=name
                    ))

        # Sort: HIGH → MEDIUM → LOW, then by current_cost descending
        priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        recommendations.sort(
            key=lambda r: (priority_order.get(r.priority, 3), -r.current_cost)
        )

        total_savings = sum(
            self._parse_savings(r.estimated_savings) for r in recommendations
        )

        summary = OptimizationSummary(
            total_potential_savings=round(total_savings, 2),
            high_priority_count=sum(1 for r in recommendations if r.priority == "HIGH"),
            medium_priority_count=sum(1 for r in recommendations if r.priority == "MEDIUM"),
            low_priority_count=sum(1 for r in recommendations if r.priority == "LOW"),
            current_period=current_period,
            previous_period=previous_period if previous_period in (available_periods or []) else None,
            total_current_spend=round(current_total, 2),
        )

        logger.info(
            "Optimization: %d recommendations generated for period %s",
            len(recommendations),
            current_period,
        )
        return OptimizationRecommendationResponse(
            summary=summary,
            recommendations=recommendations,
        )

    def _get_business_service_rows(
        self,
        billing_period: str | None,
        product: str | None = None,
        team: str | None = None,
        environment: str | None = None,
        account: str | None = None,
        region: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get service rows filtered to real business services and aggregated by business service name."""
        if not billing_period:
            return []
        raw_rows = self._query.get_service_rows_data(billing_period, product, team, environment, account, region)
        business_rows = filter_business_services(raw_rows)
        from app.services.business_cost_service import normalize_and_aggregate_services
        return normalize_and_aggregate_services(business_rows)

    def _identify_high_growth(
        self,
        current_rows: list[dict[str, Any]],
        previous_cost_map: dict[str, float],
        current_total: float,
        flagged: set[str],
    ) -> list[OptimizationRecommendation]:
        """Flag services with significant MoM cost increases."""
        recs: list[OptimizationRecommendation] = []

        for row in current_rows:
            service = row["service"]
            cost_now = row["amount"]
            cost_prev = previous_cost_map.get(service, 0.0)

            if cost_prev <= 0 or service in flagged:
                continue

            change_pct = ((cost_now - cost_prev) / cost_prev) * 100
            if change_pct < _HIGH_GROWTH_THRESHOLD_PCT:
                continue

            priority = "HIGH" if change_pct >= _SPIKE_THRESHOLD_PCT else "MEDIUM"
            share_pct = (cost_now / current_total * 100) if current_total else 0
            savings = round(cost_now * _SAVINGS_RATE, 2)

            issue = (
                f"Cost spike: +{change_pct:.1f}% increase compared to previous period"
                if change_pct >= _SPIKE_THRESHOLD_PCT
                else f"High growth: +{change_pct:.1f}% increase compared to previous period"
            )
            reason = (
                f"{service} cost increased from ${cost_prev:,.2f} to ${cost_now:,.2f} "
                f"({change_pct:+.1f}%) compared to previous period."
            )
            business_impact = (
                f"This service accounts for {share_pct:.1f}% of total cloud spend "
                f"and is growing rapidly."
            )
            action = self._get_growth_action(service)

            recs.append(OptimizationRecommendation(
                service=service,
                issue=issue,
                reason=reason,
                business_impact=business_impact,
                estimated_savings=f"${savings:,.2f}/month",
                recommended_action=action,
                priority=priority,
                current_cost=round(cost_now, 2),
                previous_cost=round(cost_prev, 2),
                change_pct=round(change_pct, 1),
            ))
            flagged.add(service)

        return recs

    def _identify_top_spenders(
        self,
        current_rows: list[dict[str, Any]],
        previous_cost_map: dict[str, float],
        current_total: float,
        flagged: set[str],
    ) -> list[OptimizationRecommendation]:
        """Flag top-N services by absolute cost that haven't been flagged yet."""
        recs: list[OptimizationRecommendation] = []
        top_rows = sorted(current_rows, key=lambda r: r["amount"], reverse=True)[:_TOP_SPEND_LIMIT]

        for row in top_rows:
            service = row["service"]
            cost_now = row["amount"]
            cost_prev = previous_cost_map.get(service)

            if service in flagged or cost_now < 10.0:  # Skip trivially small costs
                continue

            share_pct = (cost_now / current_total * 100) if current_total else 0
            savings = round(cost_now * _SAVINGS_RATE, 2)

            change_pct = None
            if cost_prev and cost_prev > 0:
                change_pct = round(((cost_now - cost_prev) / cost_prev) * 100, 1)

            priority = "HIGH" if share_pct >= 25 else "MEDIUM"
            issue = f"Top cost driver: {share_pct:.1f}% of total spend"
            reason = (
                f"{service} is one of the top AWS cost drivers at ${cost_now:,.2f}/month, "
                f"representing {share_pct:.1f}% of total cloud spend."
            )
            business_impact = (
                f"Optimizing this service could yield the highest absolute savings "
                f"(estimated ${savings:,.2f}/month)."
            )
            action = self._get_top_spender_action(service)

            recs.append(OptimizationRecommendation(
                service=service,
                issue=issue,
                reason=reason,
                business_impact=business_impact,
                estimated_savings=f"${savings:,.2f}/month",
                recommended_action=action,
                priority=priority,
                current_cost=round(cost_now, 2),
                previous_cost=round(cost_prev, 2) if cost_prev else None,
                change_pct=change_pct,
            ))
            flagged.add(service)

        return recs

    def _identify_idle_services(
        self,
        current_rows: list[dict[str, Any]],
        flagged: set[str],
    ) -> list[OptimizationRecommendation]:
        """Flag services with very low spend that may represent idle/forgotten resources."""
        recs: list[OptimizationRecommendation] = []

        for row in current_rows:
            service = row["service"]
            cost_now = row["amount"]

            if service in flagged or cost_now <= 0 or cost_now > _IDLE_COST_MAX:
                continue

            recs.append(OptimizationRecommendation(
                service=service,
                issue="Potentially idle resource: very low cost",
                reason=(
                    f"{service} incurred only ${cost_now:.4f} this month, "
                    "which may indicate idle or misconfigured resources."
                ),
                business_impact="While the direct cost is minimal, idle resources can accumulate and indicate orphaned infrastructure.",
                estimated_savings=f"${cost_now:.2f}/month",
                recommended_action=f"Review {service} usage and terminate any unused resources to eliminate unnecessary charges.",
                priority="LOW",
                current_cost=round(cost_now, 4),
                previous_cost=None,
                change_pct=None,
            ))
            flagged.add(service)

        return recs

    @staticmethod
    def _get_growth_action(service: str) -> str:
        """Return a service-specific recommended action for high-growth services."""
        service_lower = service.lower()
        if "relational database" in service_lower or "rds" in service_lower:
            return "Review RDS instance sizing, storage auto-scaling settings, and I/O usage. Consider reserved instances for predictable workloads."
        if "elastic compute" in service_lower or "ec2" in service_lower:
            return "Analyze EC2 utilization with AWS Compute Optimizer. Right-size over-provisioned instances and consider Savings Plans."
        if "simple storage" in service_lower or "s3" in service_lower:
            return "Audit S3 lifecycle policies, enable Intelligent Tiering for infrequently accessed data, and review storage class usage."
        if "lambda" in service_lower:
            return "Review Lambda invocation counts and duration. Optimize memory allocation and investigate unexpected invocation spikes."
        if "bedrock" in service_lower:
            return "Analyze Bedrock usage patterns. Implement prompt caching and review model selection for cost-performance balance."
        if "cloudfront" in service_lower:
            return "Review CloudFront data transfer costs and cache hit ratios. Optimize cache behavior to reduce origin requests."
        if "dynamodb" in service_lower:
            return "Review DynamoDB capacity mode (on-demand vs provisioned). Consider DAX caching and optimize access patterns."
        return f"Investigate recent changes to {service} usage patterns and consider right-sizing or reserved capacity."

    @staticmethod
    def _get_top_spender_action(service: str) -> str:
        """Return a service-specific recommended action for top spenders."""
        service_lower = service.lower()
        if "relational database" in service_lower or "rds" in service_lower:
            return "Evaluate RDS Reserved Instances (1-3 year) for up to 60% savings. Review multi-AZ necessity for non-production environments."
        if "elastic compute" in service_lower or "ec2" in service_lower:
            return "Purchase EC2 Savings Plans or Reserved Instances for baseline workloads. Use Spot Instances for fault-tolerant jobs."
        if "simple storage" in service_lower or "s3" in service_lower:
            return "Implement S3 lifecycle rules to transition old data to Glacier. Enable S3 Intelligent-Tiering for variable access patterns."
        if "bedrock" in service_lower:
            return "Review Bedrock model usage and implement caching strategies. Consider provisioned throughput for consistent workloads."
        return f"Conduct a detailed cost analysis for {service} and explore AWS savings plans, reserved capacity, or architectural optimizations."

    @staticmethod
    def _parse_savings(savings_str: str) -> float:
        """Parse an estimated savings string like '$45.00/month' → 45.0."""
        try:
            return float(savings_str.replace("$", "").replace("/month", "").replace(",", "").strip())
        except (ValueError, AttributeError):
            return 0.0

    @staticmethod
    def _empty_response() -> OptimizationRecommendationResponse:
        return OptimizationRecommendationResponse(
            summary=OptimizationSummary(
                total_potential_savings=0.0,
                high_priority_count=0,
                medium_priority_count=0,
                low_priority_count=0,
                current_period=None,
                previous_period=None,
                total_current_spend=0.0,
            ),
            recommendations=[],
        )

    @staticmethod
    def _get_dimension_action(dimension: str, value: str) -> str:
        if dimension == "product":
            return f"Review resource utilization and optimize instances associated with the '{value}' product line. Focus on right-sizing database instances."
        elif dimension == "team":
            return f"Coordinate with the '{value}' team to optimize their resource usage. Identify any redundant test or staging setups."
        elif dimension == "environment":
            if value == "Sandbox":
                return "Establish automated shutdown schedules for Sandbox resources during non-business hours. Enforce strict budget alerts."
            return f"Review configuration of resources running in the '{value}' environment. Right-size compute instances and delete unattached storage volumes."
        elif dimension == "region":
            return f"Consider consolidated hosting options. Check if transfer costs to/from region '{value}' can be optimized using CloudFront or regional VPC endpoints."
        elif dimension == "account":
            return f"Investigate account '{value}' for orphaned resources, unused EBS volumes, or idle EC2 instances. Implement tags to track resource ownership."
        return "Review billing trends and investigate resource utilization."
