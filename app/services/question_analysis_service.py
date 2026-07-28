"""Enterprise FinOps Copilot — Intent analysis for chatbot questions.

Provides structured intent classification with confidence scoring,
natural language month/service parsing, business hierarchy awareness,
and contextual follow-up suggestion generation.
All classification is deterministic — no LLM calls needed here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import logging
import re
from typing import Any

from app.services.cost_query_service import CostQueryService
from app.services.entity_resolver import (
    extract_service_from_text,
    extract_comparison_service_from_text,
    resolve_relative_date_range,
    get_service_category,
    get_services_in_category,
)

logger = logging.getLogger(__name__)


# ── Supported intent types ────────────────────────────────────────────────────

ANALYSIS_TYPES = {
    # Core lookups
    "SIMPLE_LOOKUP",
    "MONTH_SUMMARY",
    "GENERAL_COST_QUERY",
    # Trends
    "MONTHLY_TREND",
    "SERVICE_TREND",
    "FORECAST",
    "YEAR_SUMMARY",
    # Comparisons
    "MONTH_COMPARISON",
    "SERVICE_COMPARISON",
    "SERVICE_PRODUCTS_BREAKDOWN",
    "PRODUCT_SERVICES_BREAKDOWN",
    # Service queries
    "SERVICE_COST",
    "COST_BREAKDOWN",
    "TOP_SERVICES",
    "HIGHEST_SERVICE",
    "LOWEST_SERVICE",
    "PERCENTAGE_CONTRIBUTION",
    "MONTHLY_AVERAGE",
    "BIGGEST_CONTRIBUTOR",
    # Analytics
    "EXECUTIVE_SUMMARY",
    "BUSINESS_INSIGHTS",
    "COST_OPTIMIZATION",
    # Business hierarchy (NEW)
    "PRODUCT_ANALYSIS",
    "ENVIRONMENT_ANALYSIS",
    "REGION_ANALYSIS",
    "ACCOUNT_ANALYSIS",
    "DEVELOPER_ANALYSIS",
    "COMMON_INFRA_ANALYSIS",
    "ORGANIZATION_SUMMARY",
}

# ── Business hierarchy definitions ────────────────────────────────────────────

VALID_PRODUCTS = {"safestart": "SafeStart", "safe start": "SafeStart", "accutrain": "AccuTrain", "accu train": "AccuTrain", "accu": "AccuTrain"}

VALID_ENVIRONMENTS = {
    "qa": "QA",
    "uat": "UAT",
    "production": "Production",
    "prod": "Production",
}

VALID_DEVELOPER_ACCOUNTS = {
    "employee": "Employee",
    "trainee": "Trainee",
    "developers": "Developers",
    "developer": "Developers",
    "development": "Developers",
    "dev": "Developers",
}

VALID_COMMON_INFRA = {
    "logs": "Logs",
    "log": "Logs",
    "audit": "Audit",
    "data platform": "Data Platform",
    "sandbox": "Sandbox",
    "common infrastructure": "Common Infrastructure",
    "common infra": "Common Infrastructure",
    "infrastructure": "Common Infrastructure",
    "infra": "Common Infrastructure",
    "shared infrastructure": "Common Infrastructure",
}

# ── Month aliases ──────────────────────────────────────────────────────────────

_MONTH_ALIASES: dict[str, int] = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}

_MONTH_PATTERN = (
    r"january|jan|february|feb|march|mar|april|apr|may|june|jun|"
    r"july|jul|august|aug|september|sept|sep|october|oct|november|nov|december|dec"
)

# ── Ignored service name tokens ────────────────────────────────────────────────

_IGNORED_SERVICE_TOKENS = {
    "amazon", "aws",
    "service", "services", "the", "cloud",
}

# ── Service alias map ─────────────────────────────────────────────────────────

_SERVICE_ALIASES: dict[str, str] = {
    "s3": "simple storage", "simple storage": "simple storage",
    "ec2": "elastic compute", "elastic compute cloud": "elastic compute", "compute": "elastic compute",
    "lambda": "lambda",
    "rds": "relational database", "relational database": "relational database",
    "dynamodb": "dynamodb", "dynamo": "dynamodb",
    "bedrock": "bedrock", "claude": "bedrock", "haiku": "bedrock", "sonnet": "bedrock",
    "opus": "bedrock", "bedrock claude": "bedrock", "amazon bedrock": "bedrock",
    "ecr": "ecr", "container registry": "ecr", "elastic container registry": "ecr", "registry": "ecr",
    "ecs": "elastic container service", "elastic container service": "elastic container service",
    "eks": "elastic kubernetes", "elastic kubernetes": "elastic kubernetes",
    "mediaconvert": "mediaconvert", "media convert": "mediaconvert",
    "elemental mediaconvert": "mediaconvert", "aws mediaconvert": "mediaconvert",
    "aws elemental mediaconvert": "mediaconvert", "video processing": "mediaconvert",
    "cloudwatch": "cloudwatch", "cloud watch": "cloudwatch", "monitoring": "cloudwatch",
    "cloudfront": "cloudfront", "cloud front": "cloudfront", "cdn": "cloudfront",
    "cognito": "cognito",
    "glue": "glue", "data integration": "glue",
    "guardduty": "guardduty", "guard duty": "guardduty", "security monitoring": "guardduty",
    "backup": "backup",
    "sqs": "simple queue", "simple queue": "simple queue",
    "sns": "simple notification", "simple notification": "simple notification",
    "ses": "simple email", "simple email": "simple email",
    "kinesis": "kinesis",
    "iam": "identity",
    "route53": "route 53", "route 53": "route 53",
    "cloudformation": "cloudformation",
    "secretsmanager": "secrets manager", "secrets manager": "secrets manager",
}

# ── Intent keyword groups ─────────────────────────────────────────────────────

_OPTIMIZATION_KEYWORDS = (
    "optimize", "optimization", "optimise", "optimisation",
    "recommend", "recommendation", "recommendations",
    "save", "saving", "savings",
    "reduce", "reduction",
    "waste", "wasting", "wasteful",
    "idle", "underutilize", "underutilized", "underused",
    "cut", "cutting",
    "opportunity", "opportunities",
    "efficiency", "efficient",
    "where can", "how can i reduce",
    "cost optimization report",
)

_COMPARISON_KEYWORDS = (
    "compare", "comparison", "vs", "versus",
    "change from", "between", "diff", "difference",
    "how did", "changed", "increased", "decreased",
    "dropped",
    "dropped the most", "dropped most",
    "decreased most", "increased most",
    "biggest increase", "biggest decrease",
    "largest increase", "largest decrease",
    "why did spending decrease", "why did spending increase",
    "which increased more", "which decreased",
    "uses more", "use more", "spends more", "spend more",
    "higher", "lower", "largest", "smallest", "top", "most", "least", "more",
    "cost comparison", "usage comparison", "ranking", "rank",
    "by product", "per product", "product-wise", "product wise",
    "resources", "resource", "product", "products",
)

_TREND_KEYWORDS = (
    "trend", "historical", "over time", "timeline",
    "spending trend", "over months", "month by month",
    "history", "progression", "over the last",
    "evolution", "growth", "monthly history",
    "show me the trend", "monthly trend",
)

_EXECUTIVE_SUMMARY_KEYWORDS = (
    "executive summary", "executive report", "key observations",
    "how did we perform", "performance summary",
    "what happened this month", "overall performance",
    "business performance", "monthly report",
    "c-suite", "board report",
)

_BUSINESS_INSIGHTS_KEYWORDS = (
    "business insights", "key insights", "business interpretation",
    "insights", "what does this mean", "explain the cost",
    "business context", "cost context",
)

_HIGHEST_KEYWORDS = (
    "highest", "most expensive", "costs the most", "largest",
    "biggest", "maximum", "max", "top service",
    "leading", "dominant service",
)

_LOWEST_KEYWORDS = (
    "lowest", "least expensive", "cheapest", "smallest",
    "minimum", "min", "least costly",
)

_PERCENTAGE_KEYWORDS = (
    "percentage", "percent", "contribution", "share",
    "portion", "proportion", "how much of", "what fraction",
    "what part",
)

_AVERAGE_KEYWORDS = (
    "average", "avg", "mean", "monthly average",
    "on average", "per month on average",
)

_BIGGEST_CONTRIBUTOR_KEYWORDS = (
    "biggest contributor", "biggest driver", "main driver",
    "primary driver", "leading driver", "most impact",
    "dominant", "driving cost",
)

_ORG_SUMMARY_KEYWORDS = (
    "total company", "organization", "organisation", "company spending",
    "company cost", "company total", "total company spending",
    "all products", "all business units", "entire organization",
    "overall company",
)

# ── Confidence scoring weights ────────────────────────────────────────────────

_CONFIDENCE_HIGH = 0.90
_CONFIDENCE_MEDIUM = 0.75
_CONFIDENCE_LOW = 0.55
_CONFIDENCE_DEFAULT = 0.50

# ── Dataclasses ───────────────────────────────────────────────────────────────


@dataclass(slots=True)
class QuestionAnalysis:
    analysis_type: str
    intents: list[str] = field(default_factory=list)
    entities: dict[str, Any] = field(default_factory=dict)
    billing_period: str | None = None
    comparison_periods: list[str] = field(default_factory=list)
    service_name: str | None = None
    comparison_target: str | None = None
    year: int | None = None
    top_n: int | None = None
    confidence: float = _CONFIDENCE_DEFAULT
    resolved_service: str | None = None
    dimension: str | None = None
    dimension_value: str | None = None
    comparison_dimension: str | None = None
    comparison_value: str | None = None
    # Business hierarchy fields
    business_segment: str | None = None   # "product"|"environment"|"developer"|"common_infra"|"org"
    segment_values: list[str] = field(default_factory=list)


@dataclass
class ConversationTurn:
    """Single turn of prior conversation context."""
    intent: str | None = None
    service_name: str | None = None
    billing_period: str | None = None
    top_n: int | None = None


# ── Main service ──────────────────────────────────────────────────────────────


class QuestionAnalysisService:
    """Classify user questions into structured intent before any PostgreSQL read.

    Features:
    - 27 intent types with confidence scoring
    - Business hierarchy awareness (Products / Environments / Developers / Common Infra)
    - Natural language month parsing in any word order
    - Service alias resolution (30+ aliases, ECR/EC2-safe)
    - Conversational follow-up support
    - Follow-up suggestion generation (no LLM call)
    """

    def __init__(self, query_service: CostQueryService | None = None) -> None:
        self._query = query_service or CostQueryService()

    def analyze_question(
        self,
        question: str,
        prior_turn: ConversationTurn | None = None,
    ) -> dict[str, Any]:
        """Classify question and return a structured analysis dict."""
        return asdict(self._analyze(question, prior_turn))

    def generate_followup_suggestions(
        self,
        analysis: dict[str, Any],
        original_question: str,
        *,
        data_found: bool = True,
    ) -> list[str]:
        """Generate 2–3 contextual follow-up suggestions from the analysis result.

        Uses analysis["service_name"] (the REQUESTED service), never the retrieved
        context.service_name. This ensures suggestions are always about the service
        the user asked about — even if no data was found for that service.

        Args:
            analysis: The QuestionAnalysis dict from analyze_question()
            original_question: The raw user question string
            data_found: False when the retrieval guard found no data for the service;
                        suggestions pivot to related services in the same category.

        Fully deterministic — no LLM call.
        """
        analysis_type = analysis.get("analysis_type", "")
        # IMPORTANT: use analysis["service_name"] — the REQUESTED service
        service = analysis.get("service_name")
        period = analysis.get("billing_period")
        segment = analysis.get("business_segment")
        segment_vals = analysis.get("segment_values") or []
        segment_val = segment_vals[0] if segment_vals else None

        suggestions: list[str] = []

        # ── No-data path: suggest related services in same category ───────
        if not data_found and service:
            svc_clean = service.split("(")[0].strip()
            category = get_service_category(svc_clean)
            related = [s for s in get_services_in_category(category) if s.lower() != svc_clean.lower()]
            suggestions.append("Show top AWS services this month")
            suggestions.append("Show monthly spending trend")
            if related:
                suggestions.append(f"Show {related[0]} cost")
            return suggestions[:3]

        # ── Service-specific follow-ups ───────────────────────────────────
        if analysis_type in ("SIMPLE_LOOKUP", "SERVICE_COST") and service:
            svc = service.split("(")[0].strip()
            suggestions.append(f"Show monthly trend for {svc}")
            suggestions.append(f"Compare {svc} with previous month")
            suggestions.append(f"How can I reduce {svc} cost?")

        elif analysis_type == "SERVICE_TREND" and service:
            svc = service.split("(")[0].strip()
            suggestions.append(f"What is driving {svc} cost increase?")
            suggestions.append(f"How can I reduce {svc} cost?")
            suggestions.append(f"Compare {svc} with another service")

        elif analysis_type in ("MONTHLY_TREND", "MONTH_SUMMARY"):
            suggestions.append("Compare with previous month")
            suggestions.append("Show trend chart")
            suggestions.append("Forecast next month")
            suggestions.append("Recommend cost optimizations")

        elif analysis_type == "EXECUTIVE_SUMMARY":
            suggestions.append("Show cost optimization opportunities")
            suggestions.append("Show monthly trend for this period")
            suggestions.append("What is driving the highest cost?")

        elif analysis_type in ("MONTH_COMPARISON", "SERVICE_COMPARISON"):
            suggestions.append("Show monthly trend for the full year")
            suggestions.append("What are the top services this month?")
            suggestions.append("Show optimization opportunities")

        elif analysis_type == "COST_OPTIMIZATION":
            suggestions.append("Show executive summary for this period")
            suggestions.append("Show monthly trend")
            suggestions.append("Which service costs the most?")

        elif analysis_type == "TOP_SERVICES":
            suggestions.append("Show executive summary")
            suggestions.append("Which service has the highest trend?")
            suggestions.append("Show optimization opportunities")

        elif analysis_type in ("HIGHEST_SERVICE", "BIGGEST_CONTRIBUTOR"):
            suggestions.append("Show top 5 services")
            suggestions.append("Show monthly trend")
            suggestions.append("How can I reduce this cost?")

        # ── Business segment follow-ups ───────────────────────────────────
        elif analysis_type == "PRODUCT_ANALYSIS" and segment_val:
            other = "AccuTrain" if segment_val == "SafeStart" else "SafeStart"
            suggestions.append(f"Compare {segment_val} with {other}")
            suggestions.append(f"Show monthly trend for {segment_val}")
            suggestions.append(f"What are the top services for {segment_val}?")

        elif analysis_type == "ENVIRONMENT_ANALYSIS" and segment_val:
            suggestions.append(f"Show monthly trend for {segment_val}")
            suggestions.append(f"Which service costs the most in {segment_val}?")
            suggestions.append("Compare with Production environment")

        elif analysis_type == "COMMON_INFRA_ANALYSIS":
            suggestions.append("Which infrastructure account costs the most?")
            suggestions.append("Show monthly trend for infrastructure")
            suggestions.append("How does infrastructure compare to products?")

        elif analysis_type == "ORGANIZATION_SUMMARY":
            suggestions.append("Compare SafeStart and AccuTrain")
            suggestions.append("Show optimization opportunities")
            suggestions.append("Show monthly trend")

        elif analysis_type == "DEVELOPER_ANALYSIS":
            suggestions.append("Show top services for developer accounts")
            suggestions.append("Compare employee vs trainee spending")
            suggestions.append("Show monthly trend for developers")

        elif analysis_type == "REGION_ANALYSIS":
            suggestions.append("Which region has the highest spend?")
            suggestions.append("Show monthly trend for the top region")
            suggestions.append("Which services drive regional cost?")

        elif analysis_type == "ACCOUNT_ANALYSIS":
            suggestions.append("Show top services for this account")
            suggestions.append("Show monthly trend for this account")
            suggestions.append("Compare accounts")

        # ── Default fallback ──────────────────────────────────────────────
        if not suggestions:
            suggestions = [
                "Show top 5 services this month",
                "Show monthly spending trend",
                "What are the optimization opportunities?",
            ]

        return suggestions[:3]

    def _analyze(
        self,
        question: str,
        prior_turn: ConversationTurn | None,
    ) -> QuestionAnalysis:
        text = self._normalize(question)
        has_comparison_kw = any(kw in text for kw in _COMPARISON_KEYWORDS)
        latest_period = self._query.get_latest_billing_period()
        available_periods = self._query.get_available_periods()
        available_services = self._query.get_available_service_names()

        year = self._detect_year(text, latest_period)
        top_n = self._detect_top_n(text)
        service_name = self._detect_service_name(text, available_services)
        comparison_target = self._detect_comparison_target(text, available_services, service_name)

        if prior_turn:
            service_name, comparison_target = self._resolve_followup_service(
                text, service_name, comparison_target, prior_turn
            )

        # ── Business hierarchy detection ─────────────────────────────────
        business_segment, segment_values = self._detect_business_segment(text)

        analysis_type, confidence = self._detect_analysis_type_with_confidence(
            text, service_name, comparison_target, available_services, business_segment
        )

        billing_period, comparison_periods = self._resolve_periods(
            text, analysis_type, latest_period, available_periods, year
        )

        if prior_turn and not billing_period and latest_period:
            billing_period = prior_turn.billing_period or latest_period

        # ── Dimension detection (backward compat) ─────────────────────────
        dimension = None
        dimension_value = None
        comparison_dimension = None
        comparison_value = None

        if business_segment == "product":
            dimension = "product"
            dimension_value = segment_values[0] if segment_values else None
            if len(segment_values) >= 2:
                comparison_dimension = "product"
                comparison_value = segment_values[1]
        elif business_segment == "environment":
            dimension = "environment"
            dimension_value = segment_values[0] if segment_values else None
            if len(segment_values) >= 2:
                comparison_dimension = "environment"
                comparison_value = segment_values[1]
        elif business_segment == "developer":
            dimension = "team"
            dimension_value = segment_values[0] if segment_values else None
        elif business_segment == "common_infra":
            dimension = "shared_infrastructure"
        elif business_segment == "org":
            dimension = "organization"
        else:
            # Legacy region/account detection
            region_matches = re.findall(r"\b[a-z]{2}-[a-z]+-\d\b", text)
            if region_matches:
                dimension = "region"
                dimension_value = region_matches[0]
                if len(region_matches) >= 2:
                    comparison_dimension = "region"
                    comparison_value = region_matches[1]
            elif ("region" in text or "location" in text):
                dimension = "region"

            account_id_match = re.search(r"\b\d{12}\b", text)
            if account_id_match and not dimension:
                dimension = "account"
                dimension_value = account_id_match.group(0)
            elif not dimension:
                known_accounts = [
                    "raghavan", "chandrapandi", "akilandeshwari", "vivek", "gayathri",
                    "priyadharshini", "ambrose", "bennet", "bibin", "gnanasekar",
                    "gayanthika", "srinidhi",
                ]
                for name in known_accounts:
                    if name in text:
                        dimension = "account"
                        dimension_value = name.title()
                        break

        if dimension:
            confidence = max(confidence, 0.90)
            if comparison_value and analysis_type in ("MONTH_SUMMARY", "SERVICE_COST"):
                analysis_type = "SERVICE_COMPARISON"

        intents = self._detect_intents(text, analysis_type, service_name, comparison_target, business_segment)
        relative_date_range = self._detect_relative_date_range(text)

        entities: dict[str, Any] = {
            "services": [s for s in [service_name, comparison_target] if s],
            "billing_periods": comparison_periods if comparison_periods else ([billing_period] if billing_period else []),
            "products": segment_values if business_segment == "product" else [],
            "environments": segment_values if business_segment == "environment" else [],
            "developer_accounts": segment_values if business_segment == "developer" else [],
            "common_infra": segment_values if business_segment == "common_infra" else [],
            "regions": [dimension_value] if dimension == "region" and dimension_value else [],
            "accounts": [dimension_value] if dimension == "account" and dimension_value else [],
            "relative_date_range": relative_date_range,
        }

        analysis = QuestionAnalysis(
            analysis_type=analysis_type,
            intents=intents,
            entities=entities,
            billing_period=billing_period,
            comparison_periods=comparison_periods,
            service_name=service_name,
            comparison_target=comparison_target,
            year=year,
            top_n=top_n,
            confidence=confidence,
            dimension=dimension,
            dimension_value=dimension_value,
            comparison_dimension=comparison_dimension,
            comparison_value=comparison_value,
            business_segment=business_segment,
            segment_values=segment_values,
        )
        logger.info("[ANALYSIS] Original Question: '%s'", question)
        logger.info(
            "[ANALYSIS] Detected Service: %s | Resolved Product: %s | Resolved Env: %s | Period: %s",
            service_name,
            segment_values if business_segment == "product" else None,
            segment_values if business_segment == "environment" else None,
            billing_period,
        )
        logger.info(
            "[ANALYSIS] Comparison Intent: %s | Detected Dimension: %s | Final Analysis Type: %s | Confidence: %.2f",
            has_comparison_kw,
            dimension,
            analysis_type,
            confidence,
        )
        logger.info("Question analysis: %s", asdict(analysis))
        return analysis

    def _detect_intents(
        self,
        text: str,
        primary_intent: str,
        service_name: str | None,
        comparison_target: str | None,
        business_segment: str | None,
    ) -> list[str]:
        intents: list[str] = [primary_intent]
        has_opt = any(re.search(rf"\b{re.escape(kw)}\b", text) for kw in _OPTIMIZATION_KEYWORDS)
        has_comp = any(kw in text for kw in _COMPARISON_KEYWORDS)
        has_trend = any(kw in text for kw in _TREND_KEYWORDS) or "last" in text or "past" in text or "history" in text

        if has_opt and "COST_OPTIMIZATION" not in intents and "SAVINGS_ANALYSIS" not in intents:
            intents.append("SAVINGS_ANALYSIS")
            intents.append("COST_OPTIMIZATION")
        if has_trend and "SERVICE_TREND" not in intents and "HISTORICAL_ANALYSIS" not in intents and "MONTHLY_TREND" not in intents:
            intents.append("HISTORICAL_ANALYSIS")
        if has_comp and "SERVICE_COMPARISON" not in intents and "COMPARISON" not in intents:
            intents.append("COMPARISON")
        
        return list(dict.fromkeys(intents))

    def _detect_relative_date_range(self, text: str) -> dict[str, Any] | None:
        match_n = re.search(r"(?:last|past|previous)\s+(\d+)\s+month", text)
        if match_n:
            return {"type": "last_n_months", "months": int(match_n.group(1))}
        
        if any(kw in text for kw in ("last quarter", "past quarter", "previous quarter")):
            return {"type": "last_quarter"}
        
        if any(kw in text for kw in ("last year", "past year", "previous year", "past 12 months", "last 12 months")):
            return {"type": "past_year"}

        if any(kw in text for kw in ("current year", "this year")):
            return {"type": "current_year"}

        return None

    # ── Business hierarchy detection ────────────────────────────────────────

    def _detect_business_segment(
        self, text: str
    ) -> tuple[str | None, list[str]]:
        """Detect the business segment and values from the question.

        Returns: (segment_type, [segment_values])
        segment_type: 'product' | 'environment' | 'developer' | 'common_infra' | 'org' | None
        """
        # 1. Check for org-level keywords first (highest priority)
        if any(kw in text for kw in _ORG_SUMMARY_KEYWORDS):
            return "org", []

        # 2. Check common infra (must come before environment check)
        # Check multi-word keys first (longest first)
        matched_infra = []
        for key in sorted(VALID_COMMON_INFRA, key=len, reverse=True):
            if re.search(r"\b" + re.escape(key) + r"\b", text):
                val = VALID_COMMON_INFRA[key]
                if val not in matched_infra:
                    matched_infra.append(val)
        if matched_infra:
            return "common_infra", matched_infra

        # 3. Check products
        matched_products = []
        for key in sorted(VALID_PRODUCTS, key=len, reverse=True):
            if re.search(r"\b" + re.escape(key) + r"\b", text):
                val = VALID_PRODUCTS[key]
                if val not in matched_products:
                    matched_products.append(val)
        if matched_products:
            return "product", matched_products
        if re.search(r"\b(product|products)\b", text):
            return "product", []

        # 4. Check developers (before environments, as "developer" might overlap)
        matched_devs = []
        for key in sorted(VALID_DEVELOPER_ACCOUNTS, key=len, reverse=True):
            if re.search(r"\b" + re.escape(key) + r"\b", text):
                val = VALID_DEVELOPER_ACCOUNTS[key]
                if val not in matched_devs:
                    matched_devs.append(val)
        if matched_devs:
            return "developer", matched_devs

        # 5. Check environments
        matched_envs = []
        for key in sorted(VALID_ENVIRONMENTS, key=len, reverse=True):
            if re.search(r"\b" + re.escape(key) + r"\b", text):
                val = VALID_ENVIRONMENTS[key]
                if val not in matched_envs:
                    matched_envs.append(val)
        if matched_envs:
            return "environment", matched_envs

        return None, []

    # ── Intent detection ────────────────────────────────────────────────────

    def _detect_analysis_type_with_confidence(  # noqa: C901
        self,
        text: str,
        service_name: str | None,
        comparison_target: str | None,
        available_services: list[str],
        business_segment: str | None = None,
    ) -> tuple[str, float]:
        """Return (analysis_type, confidence_score)."""
        has_service = service_name is not None
        has_month = bool(re.search(rf"\b({_MONTH_PATTERN})\b", text))
        has_two_months = self._has_two_month_mentions(text)
        has_comparison_kw = any(kw in text for kw in _COMPARISON_KEYWORDS)
        has_trend_kw = any(kw in text for kw in _TREND_KEYWORDS)

        # 1. Organization summary
        if any(kw in text for kw in _ORG_SUMMARY_KEYWORDS):
            return "ORGANIZATION_SUMMARY", _CONFIDENCE_HIGH

        # 2. Optimization
        if any(re.search(rf"\b{re.escape(kw)}\b", text) for kw in _OPTIMIZATION_KEYWORDS):
            return "COST_OPTIMIZATION", _CONFIDENCE_HIGH

        # 3. Service Products Breakdown (Resolved Service + product/usage/comparison intent)
        comp_product_keywords = (
            "product", "products", "uses more", "use more", "spends more", "spend more",
            "higher", "lower", "largest", "smallest", "top", "most", "least", "more",
            "resource", "resources", "ranking", "rank", "between", "versus", "vs",
            "compare", "comparison", "by product", "per product"
        )
        if has_service and any(kw in text for kw in comp_product_keywords):
            return "SERVICE_PRODUCTS_BREAKDOWN", _CONFIDENCE_HIGH

        # 4. Product Services Breakdown (Resolved Product + service breakdown/ranking intent)
        if business_segment == "product" and any(kw in text for kw in ("service", "services", "contribute", "breakdown", "most", "top", "component", "resource")):
            return "PRODUCT_SERVICES_BREAKDOWN", _CONFIDENCE_HIGH

        # 5. Forecast
        if any(kw in text for kw in ("forecast", "predict", "projection", "project", "next month")):
            return "FORECAST", _CONFIDENCE_HIGH

        # 6. Executive summary
        if any(kw in text for kw in _EXECUTIVE_SUMMARY_KEYWORDS):
            return "EXECUTIVE_SUMMARY", _CONFIDENCE_HIGH

        # 7. Business insights
        if any(kw in text for kw in _BUSINESS_INSIGHTS_KEYWORDS):
            return "BUSINESS_INSIGHTS", _CONFIDENCE_MEDIUM

        # 8. Business segment intents
        if business_segment == "org":
            return "ORGANIZATION_SUMMARY", _CONFIDENCE_HIGH
        if business_segment == "common_infra":
            return "COMMON_INFRA_ANALYSIS", _CONFIDENCE_HIGH
        if business_segment == "developer":
            return "DEVELOPER_ANALYSIS", _CONFIDENCE_HIGH
        if business_segment == "product":
            if has_comparison_kw:
                return "SERVICE_COMPARISON", _CONFIDENCE_HIGH
            if has_trend_kw:
                return "SERVICE_TREND", _CONFIDENCE_HIGH
            return "PRODUCT_ANALYSIS", _CONFIDENCE_HIGH
        if business_segment == "environment":
            if has_comparison_kw:
                return "SERVICE_COMPARISON", _CONFIDENCE_HIGH
            if has_trend_kw:
                return "SERVICE_TREND", _CONFIDENCE_HIGH
            return "ENVIRONMENT_ANALYSIS", _CONFIDENCE_HIGH

        # 9. Region analysis
        region_matches = re.findall(r"\b[a-z]{2}-[a-z]+-\d\b", text)
        if region_matches or ("region" in text and has_trend_kw is False):
            if has_trend_kw:
                return "SERVICE_TREND", _CONFIDENCE_MEDIUM
            return "REGION_ANALYSIS", _CONFIDENCE_HIGH

        # 10. Service comparison
        if has_service and has_comparison_kw:
            if comparison_target:
                return "SERVICE_COMPARISON", _CONFIDENCE_HIGH
            if has_two_months:
                return "MONTH_COMPARISON", _CONFIDENCE_HIGH
            return "SERVICE_COMPARISON", _CONFIDENCE_HIGH

        # 11. Service trend
        if has_service and has_trend_kw:
            return "SERVICE_TREND", _CONFIDENCE_HIGH

        # 12. General trend
        if has_trend_kw:
            return "MONTHLY_TREND", _CONFIDENCE_MEDIUM

        # 13. Month comparison
        if has_two_months and has_comparison_kw:
            return "MONTH_COMPARISON", _CONFIDENCE_HIGH
        if has_comparison_kw and has_month:
            return "MONTH_COMPARISON", _CONFIDENCE_MEDIUM
        if re.search(r"\bchange(?:d)?\b", text) and has_two_months:
            return "MONTH_COMPARISON", _CONFIDENCE_MEDIUM

        # 14. Top-N services
        if re.search(r"\btop\s+\d+\b", text) or any(
            kw in text for kw in ("top services", "ranking", "rank", "leaders", "highest spend",
                                   "largest contributors", "largest contributor")
        ):
            return "TOP_SERVICES", _CONFIDENCE_HIGH

        # 15. Highest service
        if any(kw in text for kw in _HIGHEST_KEYWORDS):
            if not any(kw in text for kw in _BIGGEST_CONTRIBUTOR_KEYWORDS):
                if not any(kw in text for kw in ("biggest increase", "biggest decrease",
                                                   "largest increase", "largest decrease",
                                                   "contributors", "contributor")):
                    return "HIGHEST_SERVICE", _CONFIDENCE_MEDIUM

        # 16. Lowest service
        if any(kw in text for kw in _LOWEST_KEYWORDS):
            return "LOWEST_SERVICE", _CONFIDENCE_MEDIUM

        # 17. Percentage contribution
        if any(kw in text for kw in _PERCENTAGE_KEYWORDS):
            return "PERCENTAGE_CONTRIBUTION", _CONFIDENCE_MEDIUM

        # 18. Monthly average
        if any(kw in text for kw in _AVERAGE_KEYWORDS):
            return "MONTHLY_AVERAGE", _CONFIDENCE_HIGH

        # 19. Biggest contributor
        if any(kw in text for kw in _BIGGEST_CONTRIBUTOR_KEYWORDS):
            return "BIGGEST_CONTRIBUTOR", _CONFIDENCE_MEDIUM

        # 20. Cost breakdown
        if any(kw in text for kw in ("service-wise", "service wise", "breakdown", "by service", "per service")):
            return "COST_BREAKDOWN", _CONFIDENCE_MEDIUM

        # 21. Simple lookup: named service with specific month
        if has_service and has_month:
            return "SIMPLE_LOOKUP", _CONFIDENCE_HIGH

        # 22. Named service → SERVICE_COST
        if has_service:
            return "SERVICE_COST", _CONFIDENCE_HIGH

        # 23. Year mentioned
        if self._mentions_year(text):
            return "YEAR_SUMMARY", _CONFIDENCE_MEDIUM

        # 24. Summary / overview keywords (ONLY when explicitly asking for summary/overview/report/bill)
        if any(kw in text for kw in ("summary", "summarize", "overview", "cloud bill", "monthly report")):
            return "MONTH_SUMMARY", _CONFIDENCE_MEDIUM

        # 25. Default fallback
        return "GENERAL_COST_QUERY", _CONFIDENCE_DEFAULT

    # ── Period resolution ───────────────────────────────────────────────────

    def _resolve_periods(  # noqa: C901
        self,
        text: str,
        analysis_type: str,
        latest_period: str | None,
        available_periods: list[str],
        year: int | None,
    ) -> tuple[str | None, list[str]]:
        """Resolve the billing period(s) for a query.

        Priority order:
        1. Relative date expressions ("last 6 months", "last quarter") → resolved
           via entity_resolver.resolve_relative_date_range() to exact period lists
        2. Explicit month/year mentions ("January 2026")
        3. Analysis-type-based defaults (trend → last 12 months, etc.)
        """
        if not latest_period:
            return None, []

        # ── 1. Relative date resolution (highest priority for multi-period) ──
        # Apply BEFORE analysis_type routing so "last 6 months" always wins
        relative_periods = resolve_relative_date_range(
            text, available_periods, latest_period
        )
        if relative_periods is not None:
            # Relative date was detected and resolved to a list of periods
            if relative_periods:
                anchor = relative_periods[-1]  # latest period in the range
                return anchor, relative_periods
            else:
                # Expression detected but no matching DB periods — return latest
                return latest_period, [latest_period]

        # ── 2. Analysis-type-based period selection ──────────────────────────

        if analysis_type == "MONTH_COMPARISON":
            explicit_periods = self._extract_explicit_periods(text, available_periods, latest_period, year)
            if len(explicit_periods) >= 2:
                ordered = self._unique_periods(explicit_periods)
                return ordered[-1], ordered
            previous_period = self._previous_period(latest_period)
            return latest_period, [previous_period, latest_period]

        if analysis_type in ("MONTHLY_TREND", "SERVICE_TREND", "ORGANIZATION_SUMMARY"):
            if year is not None:
                year_periods = [p for p in available_periods if p.startswith(f"{year}-")]
                sorted_periods = sorted(year_periods)
                return (sorted_periods[-1] if sorted_periods else latest_period), sorted_periods
            sorted_all = sorted(available_periods)
            return latest_period, sorted_all[-12:] if len(sorted_all) >= 12 else sorted_all

        if analysis_type in ("YEAR_SUMMARY",) and year is not None:
            year_periods = sorted(p for p in available_periods if p.startswith(f"{year}-"))
            return (year_periods[-1] if year_periods else latest_period), year_periods

        if analysis_type == "TOP_SERVICES" and year is not None:
            year_periods = sorted(p for p in available_periods if p.startswith(f"{year}-"))
            target_period = year_periods[-1] if year_periods else latest_period
            return target_period, [target_period] if target_period else []

        # ── 3. Explicit month/year mention ───────────────────────────────────
        explicit_period = self._extract_explicit_period(text, available_periods, latest_period, year)
        if explicit_period:
            return explicit_period, [explicit_period]

        if self._mentions_relative_current(text):
            return latest_period, [latest_period]

        if self._mentions_relative_previous(text):
            previous_period = self._previous_period(latest_period)
            return previous_period, [previous_period]

        return latest_period, [latest_period]

    # ── Service detection ───────────────────────────────────────────────────

    def _detect_service_name(self, text: str, available_services: list[str]) -> str | None:
        """Resolve service from user text via strict alias lookup (entity_resolver).

        Replaces the old fuzzy token-scoring approach that caused EC2 → EFS
        and RDS → DMS mis-resolution.
        """
        return extract_service_from_text(text, available_services)

    def _detect_comparison_target(
        self,
        text: str,
        available_services: list[str],
        primary_service: str | None,
    ) -> str | None:
        """Resolve second service for comparison via strict alias lookup."""
        has_explicit_compare = any(kw in text for kw in _COMPARISON_KEYWORDS)
        if not has_explicit_compare:
            return None
        if not available_services:
            return None
        return extract_comparison_service_from_text(text, available_services, primary_service)

    def _resolve_followup_service(
        self,
        text: str,
        detected_service: str | None,
        detected_target: str | None,
        prior_turn: ConversationTurn,
    ) -> tuple[str | None, str | None]:
        followup_self_refs = (
            "it", "that", "same service", "that service", "the service",
            "this service", "for that", "about that",
        )
        has_self_ref = any(rf"\b{re.escape(ref)}\b" in text for ref in followup_self_refs)
        if not detected_service and has_self_ref and prior_turn.service_name:
            detected_service = prior_turn.service_name
        compare_with_pattern = re.search(
            r"\b(?:compare|vs|versus|against)\b.+\b(?:with|and|to|against)\b", text
        )
        if compare_with_pattern and has_self_ref and prior_turn.service_name and detected_service:
            if detected_service.lower() != prior_turn.service_name.lower():
                detected_target = detected_service
                detected_service = prior_turn.service_name
        return detected_service, detected_target

    # ── Year / month extraction ─────────────────────────────────────────────

    def _detect_year(self, text: str, latest_period: str | None) -> int | None:
        match = re.search(r"\b(20\d{2})\b", text)
        if match:
            return int(match.group(1))
        if any(kw in text for kw in ("this year", "current year", "annual", "yearly")) and latest_period:
            return int(latest_period.split("-")[0])
        return None

    @staticmethod
    def _detect_top_n(text: str) -> int | None:
        match = re.search(r"\btop\s+(\d+)\b", text)
        if match:
            return int(match.group(1))
        if "top" in text:
            return 10
        return None

    @classmethod
    def _extract_explicit_periods(
        cls,
        text: str,
        available_periods: list[str],
        latest_period: str,
        year: int | None,
    ) -> list[str]:
        periods: list[str] = []
        for match in re.finditer(r"\b(20\d{2})-(0?[1-9]|1[0-2])\b", text):
            period = f"{int(match.group(1))}-{int(match.group(2)):02d}"
            if period in available_periods:
                periods.append(period)
        for match in re.finditer(rf"\b({_MONTH_PATTERN})\b", text):
            month_number = _MONTH_ALIASES[match.group(1)]
            target_year = year or int(latest_period.split("-")[0])
            candidate = f"{target_year}-{month_number:02d}"
            resolved = cls._resolve_matching_period(candidate, available_periods)
            if resolved and resolved not in periods:
                periods.append(resolved)
        if "last month" in text or "previous month" in text:
            prev = cls._previous_period(latest_period)
            if prev not in periods:
                periods.append(prev)
        if "current month" in text or "this month" in text:
            if latest_period not in periods:
                periods.append(latest_period)
        return periods

    @classmethod
    def _extract_explicit_period(
        cls,
        text: str,
        available_periods: list[str],
        latest_period: str,
        year: int | None,
    ) -> str | None:
        periods = cls._extract_explicit_periods(text, available_periods, latest_period, year)
        return periods[-1] if periods else None

    @staticmethod
    def _unique_periods(periods: list[str]) -> list[str]:
        unique: list[str] = []
        for period in periods:
            if period not in unique:
                unique.append(period)
        return unique

    @staticmethod
    def _mentions_year(text: str) -> bool:
        return bool(re.search(r"\b20\d{2}\b", text)) or any(
            kw in text for kw in ("this year", "current year", "annual", "yearly")
        )

    @staticmethod
    def _has_two_month_mentions(text: str) -> bool:
        matches = re.findall(rf"\b({_MONTH_PATTERN})\b", text)
        return len(set(matches)) >= 2

    @staticmethod
    def _mentions_relative_current(text: str) -> bool:
        return any(
            kw in text for kw in (
                "current synchronized month", "latest synchronized month",
                "current month", "this month", "current period", "latest",
            )
        )

    @staticmethod
    def _mentions_relative_previous(text: str) -> bool:
        return any(kw in text for kw in ("previous month", "prior month", "last month", "previous period"))

    @staticmethod
    def _resolve_matching_period(candidate: str, available_periods: list[str]) -> str | None:
        if candidate in available_periods:
            return candidate
        candidate_year, candidate_month = candidate.split("-")
        for period in available_periods:
            if period.endswith(f"-{candidate_month}") and period.startswith(candidate_year):
                return period
        for period in available_periods:
            if period.endswith(f"-{candidate_month}"):
                return period
        return None

    @staticmethod
    def _previous_period(period: str) -> str:
        year, month = map(int, period.split("-"))
        if month == 1:
            return f"{year - 1}-12"
        return f"{year}-{month - 1:02d}"

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", " ", text.strip().lower())

    @classmethod
    def _expand_aliases(cls, text: str) -> str:
        expanded = text
        for alias in sorted(_SERVICE_ALIASES, key=len, reverse=True):
            expanded = re.sub(rf"\b{re.escape(alias)}\b", _SERVICE_ALIASES[alias], expanded)
        return expanded

    @classmethod
    def _service_match_score(cls, normalized_text: str, service_name: str) -> int:
        tokens = cls._service_tokens(service_name)
        full_normalized = cls._service_tokenize(service_name)
        score = 0
        if full_normalized and full_normalized in normalized_text:
            score += 6
        for token in tokens:
            if token and len(token) >= 3 and token in normalized_text:
                score += 2
        acronym = "".join(token[0] for token in tokens if token and token[0].isalnum())
        if acronym and len(acronym) >= 2 and acronym in normalized_text:
            score += 3
        return score

    @classmethod
    def _service_tokens(cls, service_name: str) -> list[str]:
        tokens = re.findall(r"[a-z0-9]+", service_name.lower())
        return [token for token in tokens if token not in _IGNORED_SERVICE_TOKENS]

    @classmethod
    def _service_tokenize(cls, value: str) -> str:
        return " ".join(cls._service_tokens(value))
