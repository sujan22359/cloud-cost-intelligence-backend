import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class QueryPlan:
    """Structured plan specifying user intent, target dimensions, and required data sources."""
    intent: str
    query_strategy: str
    requires_monthly_costs: bool
    requires_service_costs: bool
    requires_ai_knowledge: bool
    dimensions: Dict[str, Any] = field(default_factory=dict)
    explanation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent,
            "query_strategy": self.query_strategy,
            "requires_monthly_costs": self.requires_monthly_costs,
            "requires_service_costs": self.requires_service_costs,
            "requires_ai_knowledge": self.requires_ai_knowledge,
            "dimensions": self.dimensions,
            "explanation": self.explanation,
        }


class QueryPlannerService:
    """Lightweight deterministic Query Planner.
    
    Analyses user questions and extracted analysis entities to determine:
    1. Information requested (Intent & Dimensions)
    2. Which data sources contain the information (monthly_costs, service_costs, AI Knowledge Base)
    3. Selective query strategy to retrieve only required data
    """

    def plan_query(self, question: str, analysis: Optional[Dict[str, Any]] = None) -> QueryPlan:
        lower_q = question.lower()
        analysis = analysis or {}
        entities = analysis.get("entities") or {}

        segment_vals = analysis.get("segment_values") or []
        product = segment_vals[0] if (analysis.get("business_segment") == "product" and len(segment_vals) > 0) else None
        if not product:
            if "safestart" in lower_q or "safe start" in lower_q:
                product = "SafeStart"
            elif "accutrain" in lower_q or "accu train" in lower_q or "accu" in lower_q:
                product = "AccuTrain"

        service_name = analysis.get("service_name")
        if not service_name:
            from app.services.entity_resolver import extract_service_from_text
            service_name = extract_service_from_text(question)

        analysis_type = analysis.get("analysis_type", "GENERAL_COST_QUERY")

        logger.info("[PLANNER] Question: %s | Resolved Service: %s | Resolved Product: %s | Intent: %s", question, service_name, product, analysis_type)

        # ── 1. Pure Infrastructure / Architectural / Meeting Questions ───────
        infra_keywords = ["infrastructure", "architecture", "migration", "serverless", "pull request", "meeting", "notes", "decision"]
        is_pure_infra = (
            any(k in lower_q for k in infra_keywords)
            and not any(k in lower_q for k in ["cost", "spend", "dollar", "$", "budget", "billing", "expensive", "reduce", "decrease", "increase"])
        )
        if is_pure_infra:
            logger.info("[PLANNER] Selected Strategy: INFRASTRUCTURE_KNOWLEDGE_ONLY for question: %s", question)
            return QueryPlan(
                intent="INFRASTRUCTURE_KNOWLEDGE_ONLY",
                query_strategy="INFRASTRUCTURE_KNOWLEDGE_ONLY",
                requires_monthly_costs=False,
                requires_service_costs=False,
                requires_ai_knowledge=True,
                dimensions={"service": service_name, "product": product},
                explanation="Pure infrastructure / architectural question. Using AI Knowledge Base ONLY.",
            )

        # ── 2. Service → Product / Resource Comparison Query ──────────────────
        # If service_name entity is resolved and question has product/comparison keywords -> SERVICE_PRODUCTS_BREAKDOWN
        comp_keywords = ["product", "products", "uses more", "use more", "higher", "lower", "most", "least", "comparison", "compare", "breakdown", "resources", "resource", "between"]
        is_service_product_comparison = (
            service_name is not None
            and any(k in lower_q for k in comp_keywords)
        )
        if is_service_product_comparison:
            logger.info("[PLANNER] Selected Strategy: SERVICE_PRODUCTS_BREAKDOWN for resolved service_name=%s", service_name)
            return QueryPlan(
                intent="SERVICE_PRODUCT_COMPARISON",
                query_strategy="SERVICE_PRODUCTS_BREAKDOWN",
                requires_monthly_costs=False,
                requires_service_costs=True,
                requires_ai_knowledge=False,
                dimensions={"service": service_name, "product": product},
                explanation=f"Service usage breakdown across products for resolved service '{service_name}'. Querying service_costs table.",
            )

        # ── 3. Product → Service Breakdown Query ─────────────────────────────
        # E.g. "Which AWS services contribute most to SafeStart?" or "Top services for SafeStart"
        is_product_service_breakdown = (
            product is not None
            and any(k in lower_q for k in ["service", "services", "contribute", "breakdown", "most", "top", "component", "resource"])
        )
        if is_product_service_breakdown:
            logger.info("[PLANNER] Selected Strategy: PRODUCT_SERVICES_BREAKDOWN for product=%s", product)
            return QueryPlan(
                intent="PRODUCT_SERVICE_ANALYSIS",
                query_strategy="PRODUCT_SERVICES_BREAKDOWN",
                requires_monthly_costs=False,
                requires_service_costs=True,
                requires_ai_knowledge=False,
                dimensions={"product": product, "service": service_name},
                explanation=f"Product-to-service cost breakdown for product '{product}'. Querying service_costs table.",
            )

        # ── 4. Business Explanation / Why Questions ───────────────────────────
        # E.g. "Why did EC2 costs reduce after January 2026?"
        is_why_question = any(k in lower_q for k in ["why", "reason", "cause", "explain", "how come", "dropped", "reduced", "decreased", "increased", "spiked"])
        if is_why_question:
            logger.info("QueryPlanner: Selected BUSINESS_EXPLANATION for question: %s", question)
            return QueryPlan(
                intent="BUSINESS_EXPLANATION",
                query_strategy="SERVICE_COSTS_AND_KNOWLEDGE",
                requires_monthly_costs=False,
                requires_service_costs=True,
                requires_ai_knowledge=True,
                dimensions={"service": service_name, "product": product},
                explanation="Explanation question. Querying service_costs + retrieving AI Knowledge Base entries.",
            )

        # ── 5. Executive Summary ──────────────────────────────────────────────
        # E.g. "Summarize our AWS optimization journey"
        is_exec_summary = any(k in lower_q for k in ["executive summary", "journey", "optimization journey", "summarize", "overview"])
        if is_exec_summary or analysis_type == "EXECUTIVE_SUMMARY":
            logger.info("QueryPlanner: Selected EXECUTIVE_SUMMARY strategy")
            return QueryPlan(
                intent="EXECUTIVE_SUMMARY",
                query_strategy="EXECUTIVE_SUMMARY",
                requires_monthly_costs=True,
                requires_service_costs=True,
                requires_ai_knowledge=True,
                dimensions={},
                explanation="Executive summary request. Combining monthly_costs, service_costs, and AI Knowledge Base.",
            )

        # ── 6. Top Services Overall Query ─────────────────────────────────────
        # E.g. "What are the top AWS services this month?"
        if analysis_type in ("TOP_SERVICES", "HIGHEST_SERVICE", "COST_BREAKDOWN") and not product:
            logger.info("QueryPlanner: Selected TOP_SERVICES_OVERALL strategy")
            return QueryPlan(
                intent="TOP_SERVICES",
                query_strategy="TOP_SERVICES_OVERALL",
                requires_monthly_costs=False,
                requires_service_costs=True,
                requires_ai_knowledge=False,
                dimensions={"service": service_name},
                explanation="Top services overall. Querying service_costs table.",
            )

        # ── 7. Monthly Cost Trend Query ───────────────────────────────────────
        # E.g. "Show monthly spending trend"
        if analysis_type in ("MONTHLY_TREND", "YEAR_SUMMARY") and not service_name and not product:
            logger.info("QueryPlanner: Selected MONTHLY_TREND_ONLY strategy")
            return QueryPlan(
                intent="MONTHLY_TREND",
                query_strategy="MONTHLY_TREND_ONLY",
                requires_monthly_costs=True,
                requires_service_costs=False,
                requires_ai_knowledge=False,
                dimensions={},
                explanation="Monthly cost trend query. Querying monthly_costs table ONLY.",
            )

        # Default Fallback Strategy
        logger.info("QueryPlanner: Selected STANDARD_COST_LOOKUP default strategy for intent=%s", analysis_type)
        return QueryPlan(
            intent=analysis_type,
            query_strategy="STANDARD_COST_LOOKUP",
            requires_monthly_costs=True,
            requires_service_costs=True,
            requires_ai_knowledge=True,
            dimensions={"service": service_name, "product": product},
            explanation="Standard query lookup. Utilizing available cost data and AI Knowledge context.",
        )
