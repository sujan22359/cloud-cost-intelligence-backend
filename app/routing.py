"""Enterprise FinOps Copilot — Question routing.

Routes every question to the PostgreSQL-backed intent dispatch flow.
Implements:
- Full intent dispatch for 27 analysis types
- Business hierarchy routing (Products / Environments / Developers / Common Infra / Org)
- Per-intent LLM prompt selection
- Contextual follow-up suggestion generation
- Conversational follow-up via ConversationSession

All data is read from PostgreSQL via BusinessCostService. Never from Cost Explorer directly.
"""

import logging
import re
from typing import Any

from app.services.business_cost_service import BusinessCostService, resolve_service_name_alias
from app.services.conversation_context import ConversationSession, ConversationTurn
from app.services.cost_query_service import CostQueryService
from app.services.question_analysis_service import QuestionAnalysisService

logger = logging.getLogger(__name__)

# Questions with confidence below this threshold return a clarifying question
_CLARIFICATION_THRESHOLD = 0.50


# ── Markdown cleaning ─────────────────────────────────────────────────────────


def strip_markdown_headings(text: str) -> str:
    """Remove markdown heading tokens and lone bold markers from LLM output.

    Converts:
      ### Summary  →  Summary
      **Key Findings**  →  Key Findings
    while preserving normal inline bold usage like "**$12.34**".
    """
    if not text:
        return ""
    lines = text.split("\n")
    cleaned: list[str] = []
    for line in lines:
        stripped = line.strip()
        heading_match = re.match(r"^#+\s+(.*)", stripped)
        if heading_match:
            header_text = re.sub(r"^\*\*|\*\*$|^\*|\*$", "", heading_match.group(1)).strip()
            if header_text:
                cleaned.extend(["", header_text, ""])
        else:
            bold_match = re.match(r"^\*\*(.*?)\*\*\s*$", stripped)
            if bold_match:
                header_text = bold_match.group(1).strip()
                cleaned.extend(["", header_text, ""])
            else:
                cleaned.append(line)

    result = "\n".join(cleaned)
    while "\n\n\n" in result:
        result = result.replace("\n\n\n", "\n\n")
    return result.strip()


def format_period_to_friendly(period: str) -> str:
    """Convert YYYY-MM to Month YYYY."""
    parts = period.split("-")
    if len(parts) != 2:
        return period
    year, month = parts
    months = {
        "01": "January", "02": "February", "03": "March", "04": "April",
        "05": "May", "06": "June", "07": "July", "08": "August",
        "09": "September", "10": "October", "11": "November", "12": "December"
    }
    return f"{months.get(month, month)} {year}"


def clean_meaningless_percentages(text: str, context: dict[str, Any] | None) -> str:
    """Remove 100% percentages from output when context contains only one service."""
    if not text or not context:
        return text

    # Determine unique service count
    num_services = 0
    if "top_services" in context and isinstance(context["top_services"], list):
        num_services = len(context["top_services"])
    elif "services" in context and isinstance(context["services"], list):
        num_services = len(context["services"])
    elif "breakdown" in context and isinstance(context["breakdown"], list):
        num_services = len(context["breakdown"])
    elif "history" in context and isinstance(context["history"], list):
        num_services = 1

    if num_services == 1:
        text = re.sub(r"\s*\(\s*\+?-?100(?:\.0+)?\s*%\s*(?:of\s+total)?\s*(?:spend)?\)", "", text)
        text = re.sub(r"\b100(?:\.0+)?\s*%\s*(?:of\s+total)?\s*(?:spend)?\b", "", text)

    return text


# ── Router ────────────────────────────────────────────────────────────────────


class QuestionRouter:
    """Route questions to PostgreSQL-backed cost data via structured intent dispatch.

    Each QuestionRouter instance holds a ConversationSession so that follow-up
    questions inherit context from the prior turn.
    """

    def __init__(
        self,
        llm_service: Any,
        cost_query_service: CostQueryService | None = None,
        business_cost_service: BusinessCostService | None = None,
        analysis_service: QuestionAnalysisService | None = None,
    ) -> None:
        self._llm = llm_service
        self._cost_query = cost_query_service or CostQueryService()
        self._business_cost = business_cost_service or BusinessCostService(query_service=self._cost_query)
        self._analysis = analysis_service or QuestionAnalysisService(query_service=self._cost_query)
        self._session = ConversationSession()

    def answer(self, question: str, top_k: int = 5) -> dict[str, Any]:
        """Route the question to the best data source and return a dashboard-ready answer."""
        return self._answer_cost(question)

    def _answer_cost(self, question: str) -> dict[str, Any]:
        logger.info("Selected Route: cost (PostgreSQL)")

        # ── Step 1: Run Query Planner & Analyze Question ──────────────────────
        analysis = None
        try:
            analysis = self._analysis.analyze_question(question, prior_turn=self._session.last_turn)
        except Exception as exc:
            logger.warning("Question analysis failed: %s", exc)

        from app.services.query_planner_service import QueryPlannerService
        planner = QueryPlannerService()
        plan = planner.plan_query(question, analysis)
        logger.info(
            "Query Plan generated: strategy=%s, sources=[monthly=%s, service=%s, knowledge=%s]",
            plan.query_strategy, plan.requires_monthly_costs, plan.requires_service_costs, plan.requires_ai_knowledge
        )

        # ── Step 2: Selectively Retrieve AI Knowledge ────────────────────────
        relevant_knowledge_dicts: list[dict[str, Any]] = []
        if plan.requires_ai_knowledge:
            try:
                from app.db.session import SessionLocal
                from app.services.knowledge_retrieval_service import KnowledgeRetrievalService
                with SessionLocal() as db:
                    retrieval_svc = KnowledgeRetrievalService()
                    relevant_knowledge = retrieval_svc.retrieve_relevant_knowledge(db, question, top_n=3)
                    if relevant_knowledge:
                        relevant_knowledge_dicts = [k.to_dict() for k in relevant_knowledge]
                        logger.info("Retrieved %d relevant AI Knowledge entries for query.", len(relevant_knowledge_dicts))
            except Exception as exc:
                logger.warning("Failed to retrieve AI Knowledge: %s", exc)

        # ── Step 3: Execute Target Query Based on Query Strategy ─────────────
        context: dict[str, Any] | None = None
        b_period = analysis.get("billing_period") if analysis else None

        if plan.query_strategy == "PRODUCT_SERVICES_BREAKDOWN":
            prod_target = plan.dimensions.get("product")
            if prod_target:
                context = self._cost_query.get_top_services_for_product(prod_target, billing_period=b_period)
                if context:
                    context["analysis_type_hint"] = "SERVICE_COST"

        elif plan.query_strategy == "SERVICE_PRODUCTS_BREAKDOWN":
            svc_target = plan.dimensions.get("service")
            if svc_target:
                context = self._cost_query.get_product_breakdown_for_service(svc_target, billing_period=b_period)
                if context:
                    context["analysis_type_hint"] = "SERVICE_COMPARISON"

        elif plan.query_strategy == "INFRASTRUCTURE_KNOWLEDGE_ONLY":
            context = {
                "analysis": "infrastructure_knowledge",
                "analysis_type_hint": "BUSINESS_INSIGHTS",
            }

        # Fallback to standard context resolution if context not produced by strategy
        if context is None and plan.query_strategy != "INFRASTRUCTURE_KNOWLEDGE_ONLY":
            context, analysis = self._resolve_cost_context_with_analysis(question)

        # ── Step 4: Evaluate AWS Cost Data Guards ─────────────────────────────
        guard_response = self._check_data_limitations(question) if plan.query_strategy != "INFRASTRUCTURE_KNOWLEDGE_ONLY" else None
        validation_error = self._validate_retrieved_context(question, analysis, context) if (context and not guard_response and plan.query_strategy != "INFRASTRUCTURE_KNOWLEDGE_ONLY") else None

        has_valid_cost_data = (
            context is not None
            and guard_response is None
            and validation_error is None
        )
        has_ai_knowledge = len(relevant_knowledge_dicts) > 0

        # ── Step 5: Handle Routing Scenarios ──────────────────────────────────
        if has_valid_cost_data:
            # Case 1 (Cost + Knowledge) & Case 3 (Cost only)
            if has_ai_knowledge:
                context["ai_knowledge"] = relevant_knowledge_dicts
        elif has_ai_knowledge:
            # Case 2: Cost Data Missing / Guarded BUT AI Knowledge Available
            logger.info("Cost data unavailable/guarded, but AI Knowledge exists. Fallback to AI Knowledge context.")
            cost_note = "No matching AWS cost records were found for the requested service or period."
            if validation_error and isinstance(validation_error, dict):
                cost_note = validation_error.get("explanation") or validation_error.get("answer") or cost_note
            elif guard_response and isinstance(guard_response, dict):
                cost_note = guard_response.get("explanation") or guard_response.get("answer") or cost_note

            context = {
                "analysis": analysis.get("intent", "GENERAL_COST_QUERY") if analysis else "GENERAL_COST_QUERY",
                "cost_data_note": cost_note,
                "ai_knowledge": relevant_knowledge_dicts,
            }
        else:
            # Case 4: Both Cost Data AND AI Knowledge Missing
            logger.info("Neither Cost Data nor AI Knowledge available for question: %s", question)
            if guard_response:
                return self._response(
                    question=question,
                    route="cost",
                    answer=guard_response["answer"],
                    explanation=guard_response["explanation"],
                    sources=[{"source": "PostgreSQL Cost Data"}],
                    suggestions=guard_response["suggestions"],
                )
            if validation_error:
                return self._response(
                    question=question,
                    route="cost",
                    answer=validation_error["answer"],
                    explanation=validation_error["explanation"],
                    sources=[{"source": "PostgreSQL Cost Data"}],
                    suggestions=validation_error["suggestions"],
                )
            return self._response(
                question=question,
                route="cost",
                answer="This information is not available in the current dataset.",
                explanation=(
                    "The billing database and AI Knowledge Base do not contain records that match this query. "
                    "This may be because the requested billing period has not yet been synchronized, "
                    "the requested entity does not appear in the current cost data, "
                    "or the question is outside the scope of the available dataset."
                ),
                sources=[],
                suggestions=[
                    "Show total AWS spend for the latest billing period",
                    "Which product had the highest cost this month?",
                    "Show monthly spending trend for the past 6 months",
                ],
            )

        analysis_type = context.get("analysis", "")
        logger.info("[ROUTER] Strategy: %s | Analysis Type: %s | Context Keys: %s", plan.query_strategy, analysis_type, list(context.keys()))
        logger.info("[PROMPT CONTEXT] %s", context)

        # ── Step 6: Generate answer using per-intent prompt ──────────────────
        if hasattr(self._llm, "generate_intent_answer"):
            answer, explanation = self._llm.generate_intent_answer(question, context, analysis_type)
        elif analysis_type == "optimization_context":
            answer, explanation = self._llm.generate_optimization_answer(question, context)
        else:
            answer, explanation = self._llm.generate_cost_insights(question, context)

        answer = strip_markdown_headings(answer)
        explanation = strip_markdown_headings(explanation)
        answer = clean_meaningless_percentages(answer, context)
        explanation = clean_meaningless_percentages(explanation, context)

        # ── Generate follow-up suggestions ──────────────────────────────────
        suggestions: list[str] = []
        if analysis:
            # Pass data_found=True always here (validation_error path returns early)
            suggestions = self._analysis.generate_followup_suggestions(
                analysis, question, data_found=True
            )

        return self._response(
            question=question,
            route="cost",
            answer=answer,
            explanation=explanation,
            sources=[{"source": "PostgreSQL Cost Data"}],
            suggestions=suggestions,
        )

    def _check_data_limitations(self, question: str) -> dict[str, Any] | None:
        """Inspect the question and database to enforce the Data-Aware Response Guard."""
        try:
            available_periods = self._cost_query.get_available_periods()
        except Exception:
            available_periods = []

        if not available_periods:
            return {
                "answer": "No billing data is currently available. Please ensure the historical sync has completed.",
                "explanation": "The monthly billing database contains no records.",
                "suggestions": ["Check data sync status"]
            }

        earliest_p = available_periods[-1]
        latest_p = available_periods[0]
        total_months = len(available_periods)

        friendly_start = format_period_to_friendly(earliest_p)
        friendly_end = format_period_to_friendly(latest_p)

        lower_q = question.lower()

        # 1. Check for year-long / 12-month trend queries when data is insufficient
        if ("year" in lower_q or "yoy" in lower_q or "12 month" in lower_q or "yearly" in lower_q) and total_months < 12:
            is_year_req = any(x in lower_q for x in ["past year", "last year", "one year", "1 year", "12 month", "yoy", "yearly"])
            if is_year_req:
                ans = (
                    f"I currently have billing data from {friendly_start} through {friendly_end}. "
                    "A one-year comparison cannot be generated because historical data is unavailable. "
                    f"I can instead analyse the available {total_months}-month trend."
                )
                exp = (
                    f"The database contains cost data from {friendly_start} to {friendly_end} "
                    f"({total_months} months total). No data exists prior to {friendly_start}."
                )
                return {
                    "answer": ans,
                    "explanation": exp,
                    "suggestions": [
                        f"Show cost trend from {friendly_start} to {friendly_end}",
                        "Show latest month summary",
                        "Recommend cost optimizations"
                    ]
                }

        # 2. Check for queries targeting specific months not in available periods
        months_regex = (
            r"(january|february|march|april|may|june|july|august|september|october|november|december|"
            r"jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)"
        )
        month_year_matches = re.findall(rf"\b{months_regex}\s+(\d{{4}})\b", lower_q)
        ym_matches = re.findall(r"\b(20\d{2})-(0[1-9]|1[0-2])\b", lower_q)
        year_matches = re.findall(r"\b(202[0-9])\b", lower_q)

        requested_periods = []
        month_name_map = {
            "january": "01", "jan": "01", "february": "02", "feb": "02",
            "march": "03", "mar": "03", "april": "04", "apr": "04",
            "may": "05", "june": "06", "jun": "06", "july": "07", "jul": "07",
            "august": "08", "aug": "08", "september": "09", "sep": "09",
            "october": "10", "oct": "10", "november": "11", "nov": "11",
            "december": "12", "dec": "12"
        }
        for m_name, y_val in month_year_matches:
            m_num = month_name_map.get(m_name)
            if m_num:
                requested_periods.append(f"{y_val}-{m_num}")
        for y_val, m_num in ym_matches:
            requested_periods.append(f"{y_val}-{m_num}")

        for req_p in requested_periods:
            if req_p not in available_periods:
                friendly_req = format_period_to_friendly(req_p)
                ans = (
                    f"I currently have billing data from {friendly_start} through {friendly_end}. "
                    f"The period {friendly_req} cannot be analysed because historical data is unavailable. "
                    f"I can instead analyse the available {total_months}-month trend or focus on {friendly_end}."
                )
                exp = (
                    f"The requested billing period {friendly_req} is outside the range of available "
                    f"data in the database ({friendly_start} to {friendly_end})."
                )
                return {
                    "answer": ans,
                    "explanation": exp,
                    "suggestions": [
                        f"Show cost trend from {friendly_start} to {friendly_end}",
                        f"Show summary for {friendly_end}",
                        "Recommend cost optimizations"
                    ]
                }

        # 3. Check for specific years outside the available data range
        for yr in year_matches:
            if not any(period.startswith(yr) for period in available_periods):
                ans = (
                    f"I currently have billing data from {friendly_start} through {friendly_end}. "
                    f"The year {yr} cannot be analysed because historical data is unavailable. "
                    f"I can instead analyse the available {total_months}-month trend or focus on {friendly_end}."
                )
                exp = (
                    f"The requested year {yr} is outside the range of available "
                    f"data in the database ({friendly_start} to {friendly_end})."
                )
                return {
                    "answer": ans,
                    "explanation": exp,
                    "suggestions": [
                        f"Show cost trend from {friendly_start} to {friendly_end}",
                        f"Show summary for {friendly_end}",
                        "Recommend cost optimizations"
                    ]
                }

        return None

    def _validate_retrieved_context(
        self,
        question: str,
        analysis: dict[str, Any] | None,
        context: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Validate that the retrieved context actually contains the requested service.

        Enforces canonical name matching: if the user asked for EC2 but the context
        contains EFS data (or no data), the guard fires and returns an honest response.
        Never silently substitutes a different service.
        """
        if not analysis:
            return None

        entities = analysis.get("entities") or {}
        requested_services = entities.get("services") or []
        if not requested_services and analysis.get("service_name"):
            requested_services = [analysis["service_name"]]

        for req_svc in requested_services:
            clean_svc = req_svc.split("(")[0].strip()

            # No context at all — service not found
            if not context:
                svc_suggestions = [
                    "Show top services this month",
                    "Show monthly spending trend",
                    "Recommend cost optimizations",
                ]
                if analysis:
                    svc_suggestions = self._analysis.generate_followup_suggestions(
                        analysis, question, data_found=False
                    )
                return {
                    "answer": f"No billing spend was recorded for **{clean_svc}** in the available dataset.",
                    "explanation": f"The service {clean_svc} has no matching cost records in PostgreSQL.",
                    "suggestions": svc_suggestions,
                }

            # Context exists — verify the service name matches canonically
            from app.services.entity_resolver import resolve_canonical_service  # noqa: PLC0415
            requested_canonical = resolve_canonical_service(clean_svc) or clean_svc
            requested_canonical_lower = requested_canonical.lower()

            has_service_match = False

            # Check context.service (the service returned from the query)
            ctx_service = context.get("service") or context.get("service_name") or ""
            if ctx_service:
                ctx_canonical = resolve_canonical_service(ctx_service) or ctx_service
                if ctx_canonical.lower() == requested_canonical_lower:
                    has_service_match = True

            # Check context.history entries (for trend queries)
            if not has_service_match and context.get("history"):
                # history is present — verify context.service is for the right service
                # If context.service matches, history is for the correct service
                if ctx_service and (resolve_canonical_service(ctx_service) or ctx_service).lower() == requested_canonical_lower:
                    has_service_match = True

            # Check top_services list
            if not has_service_match and context.get("top_services"):
                for svc_entry in context["top_services"]:
                    entry_name = svc_entry.get("service_name", "") or svc_entry.get("service", "")
                    if entry_name:
                        entry_canonical = (resolve_canonical_service(entry_name) or entry_name).lower()
                        if entry_canonical == requested_canonical_lower:
                            has_service_match = True
                            break

            # Check breakdown list
            if not has_service_match and context.get("breakdown"):
                for b_entry in context["breakdown"]:
                    entry_name = b_entry.get("service", "") or b_entry.get("service_name", "")
                    if entry_name:
                        entry_canonical = (resolve_canonical_service(entry_name) or entry_name).lower()
                        if entry_canonical == requested_canonical_lower:
                            has_service_match = True
                            break

            # Multi-intent compound and target breakdown contexts bypass per-service validation
            if not has_service_match and context.get("analysis") in (
                "multi_part_compound",
                "product_service_comparison",
                "service_products_breakdown",
                "product_services_breakdown",
            ):
                has_service_match = True

            if not has_service_match and analysis.get("service_name"):
                svc_suggestions = self._analysis.generate_followup_suggestions(
                    analysis, question, data_found=False
                )
                return {
                    "answer": f"No billing spend was recorded for **{clean_svc}** in the available dataset.",
                    "explanation": (
                        f"The service {clean_svc} has no cost data for the requested period. "
                        "No substitute service data will be shown."
                    ),
                    "suggestions": svc_suggestions,
                }

        return None

    def _resolve_cost_context_with_analysis(
        self, question: str
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Classify the question and fetch matching structured data.

        Returns (context, analysis_dict) tuple.
        """
        prior_turn: ConversationTurn | None = self._session.last_turn

        try:
            analysis = self._analysis.analyze_question(question, prior_turn=prior_turn)
        except Exception as exc:
            logger.warning("Analysis service failed, using month summary fallback: %s", exc)
            return self._business_cost.get_month_summary(), None

        self._session.push(self._session.build_turn_from_analysis(analysis))

        analysis_type = analysis.get("analysis_type", "MONTH_SUMMARY")
        billing_period = analysis.get("billing_period")
        comparison_periods = analysis.get("comparison_periods") or []
        service_name = analysis.get("service_name")
        comparison_target = analysis.get("comparison_target")
        top_n = analysis.get("top_n") or 5
        year = analysis.get("year")
        confidence = analysis.get("confidence", 0.5)
        business_segment = analysis.get("business_segment")
        segment_values = analysis.get("segment_values") or []
        segment_val = segment_values[0] if segment_values else None

        logger.info(
            "Analysis: type=%s | period=%s | service=%s | segment=%s(%s) | confidence=%.2f",
            analysis_type, billing_period, service_name, business_segment, segment_val, confidence,
        )

        # Low-confidence fallback
        if confidence < _CLARIFICATION_THRESHOLD:
            logger.info("Low confidence (%.2f) — returning clarification request", confidence)
            return {
                "analysis": "clarification",
                "question": question,
                "message": (
                    "Could you clarify your question? For example: "
                    "\"Show me EC2 cost in May\", \"Compare May and June\", or \"Top 5 services\"."
                ),
            }, analysis

        # ── Multi-intent compound & retrieval planning ──────────────────────
        intents = analysis.get("intents") or [analysis_type]
        if "HISTORICAL_ANALYSIS" in intents and ("SAVINGS_ANALYSIS" in intents or "COST_OPTIMIZATION" in intents) and service_name:
            logger.info("Multi-intent routing: HISTORICAL_ANALYSIS + SAVINGS_ANALYSIS for %s", service_name)
            service_ctx = self._fetch_service_context(service_name, billing_period, comparison_periods)
            opt_ctx = self._business_cost.get_optimization_context()
            
            service_opts = []
            if opt_ctx and "recommendations" in opt_ctx:
                target_alias = resolve_service_name_alias(service_name).lower()
                service_opts = [
                    rec for rec in opt_ctx.get("recommendations", [])
                    if target_alias in rec.get("service", "").lower()
                ]

            combined_ctx = {
                "analysis": "multi_part_compound",
                "analysis_type_hint": "MULTI_PART_COMPOUND",
                "service_name": resolve_service_name_alias(service_name),
                "billing_period": billing_period,
                "history": service_ctx.get("history") if service_ctx else [],
                "service_summary": service_ctx.get("summary") if service_ctx else {},
                "optimization_opportunities": service_opts or (opt_ctx.get("recommendations", []) if opt_ctx else []),
                "monthly_trend": self._business_cost.get_monthly_trend(limit=6),
            }
            return combined_ctx, analysis

        if business_segment == "product" and len(segment_values) >= 2 and service_name:
            logger.info("Multi-intent product service comparison: %s vs %s for service %s", segment_values[0], segment_values[1], service_name)
            from app.schemas.cost_schema import DimensionType  # noqa: PLC0415
            ctx_a = self._business_cost.get_dimension_trend(DimensionType.PRODUCT, segment_values[0])
            ctx_b = self._business_cost.get_dimension_trend(DimensionType.PRODUCT, segment_values[1])
            combined_ctx = {
                "analysis": "product_service_comparison",
                "analysis_type_hint": "SERVICE_COMPARISON",
                "service_name": resolve_service_name_alias(service_name),
                "product_a": segment_values[0],
                "product_b": segment_values[1],
                "product_a_trend": ctx_a,
                "product_b_trend": ctx_b,
                "billing_period": billing_period,
            }
            return combined_ctx, analysis

        # ── Business hierarchy routing ─────────────────────────────────────

        if business_segment == "org":
            logger.info("Routing: organization_summary")
            ctx = self._business_cost.get_organization_summary(billing_period=billing_period)
            if ctx:
                ctx["analysis_type_hint"] = "ORGANIZATION_SUMMARY"
            return ctx, analysis

        if business_segment == "common_infra":
            logger.info("Routing: common_infra_analysis")
            ctx = self._business_cost.get_shared_infrastructure_analysis(billing_period=billing_period)
            if ctx:
                ctx["analysis_type_hint"] = "COMMON_INFRA_ANALYSIS"
            return ctx, analysis

        if business_segment == "developer":
            logger.info("Routing: developer_analysis for %s", segment_val)
            ctx = self._business_cost.get_developer_analysis(
                billing_period=billing_period,
            )
            if ctx:
                ctx["analysis_type_hint"] = "DEVELOPER_ANALYSIS"
                ctx["segment_filter"] = "developer"
            return ctx, analysis

        if business_segment == "product":
            logger.info("Routing: product_analysis for %s", segment_val or "(all products)")
            from app.schemas.cost_schema import DimensionType  # noqa: PLC0415
            if len(segment_values) >= 2 and analysis_type in ("SERVICE_COMPARISON",):
                ctx = self._business_cost.get_dimension_comparison(
                    dimension=DimensionType.PRODUCT,
                    item_a=segment_values[0],
                    item_b=segment_values[1],
                    billing_period=billing_period,
                )
                if ctx:
                    ctx["analysis_type_hint"] = "SERVICE_COMPARISON"
                return ctx, analysis
            if analysis_type in ("SERVICE_TREND", "MONTHLY_TREND") and segment_val:
                ctx = {
                    "analysis": "product_trend",
                    "item": segment_val,
                    "trend": self._business_cost.get_dimension_trend(
                        dimension=DimensionType.PRODUCT,
                        item=segment_val,
                    ),
                    "analysis_type_hint": "SERVICE_TREND",
                }
                return ctx, analysis
            # Generic product query (no specific product name mentioned) — return full breakdown ranked by cost
            if not segment_val:
                logger.info("Routing: generic product breakdown (no specific product name)")
                breakdown = self._business_cost.get_dimension_breakdown(
                    dimension=DimensionType.PRODUCT,
                    billing_period=billing_period,
                )
                ctx = {
                    "analysis": "product_breakdown",
                    "analysis_type_hint": "PRODUCT_ANALYSIS",
                    "billing_period": billing_period,
                    "breakdown": breakdown or [],
                    "segment_filter": None,
                }
                return ctx, analysis
            ctx = self._business_cost.get_dimension_summary(
                dimension=DimensionType.PRODUCT,
                billing_period=billing_period,
            )
            if ctx:
                ctx["analysis_type_hint"] = "PRODUCT_ANALYSIS"
                ctx["segment_filter"] = segment_val
            return ctx, analysis

        if business_segment == "environment":
            logger.info("Routing: environment_analysis for %s", segment_val)
            from app.schemas.cost_schema import DimensionType  # noqa: PLC0415
            if len(segment_values) >= 2 and analysis_type in ("SERVICE_COMPARISON",):
                ctx = self._business_cost.get_dimension_comparison(
                    dimension=DimensionType.ENVIRONMENT,
                    item_a=segment_values[0],
                    item_b=segment_values[1],
                    billing_period=billing_period,
                )
                if ctx:
                    ctx["analysis_type_hint"] = "SERVICE_COMPARISON"
                return ctx, analysis
            if analysis_type in ("SERVICE_TREND", "MONTHLY_TREND") and segment_val:
                ctx = {
                    "analysis": "environment_trend",
                    "item": segment_val,
                    "trend": self._business_cost.get_dimension_trend(
                        dimension=DimensionType.ENVIRONMENT,
                        item=segment_val,
                    ),
                    "analysis_type_hint": "SERVICE_TREND",
                }
                return ctx, analysis
            ctx = self._business_cost.get_dimension_summary(
                dimension=DimensionType.ENVIRONMENT,
                billing_period=billing_period,
            )
            if ctx:
                ctx["analysis_type_hint"] = "ENVIRONMENT_ANALYSIS"
                ctx["segment_filter"] = segment_val
            return ctx, analysis

        # ── Dimension (region / account) routing ─────────────────────────
        dimension = analysis.get("dimension")
        dimension_val = analysis.get("dimension_value")
        comp_dim = analysis.get("comparison_dimension")
        comp_val = analysis.get("comparison_value")

        if dimension == "region":
            logger.info("Routing: region_analysis")
            from app.schemas.cost_schema import DimensionType  # noqa: PLC0415
            region_breakdown = self._business_cost.get_dimension_breakdown(
                dimension=DimensionType.REGION,
                billing_period=billing_period,
            )
            region_accounts = self._business_cost.get_region_accounts_breakdown(
                billing_period=billing_period,
            )
            region_services = self._business_cost.get_region_services_breakdown(
                billing_period=billing_period,
            )
            if comp_val and dimension_val:
                ctx = self._business_cost.get_dimension_comparison(
                    dimension=DimensionType.REGION,
                    item_a=dimension_val,
                    item_b=comp_val,
                    billing_period=billing_period,
                )
            elif dimension_val:
                ctx = {
                    "analysis": "region_breakdown",
                    "billing_period": billing_period,
                    "breakdown": region_breakdown,
                    "region_accounts": region_accounts,
                    "region_services": region_services,
                    "region": dimension_val,
                }
            else:
                ctx = {
                    "analysis": "region_breakdown",
                    "billing_period": billing_period,
                    "breakdown": region_breakdown,
                    "region_accounts": region_accounts,
                    "region_services": region_services,
                }
            if ctx:
                ctx["analysis_type_hint"] = "REGION_ANALYSIS"
            return ctx, analysis

        if dimension == "account":
            logger.info("Routing: account_analysis for %s", dimension_val)
            from app.schemas.cost_schema import DimensionType  # noqa: PLC0415
            ctx = {
                "analysis": "account_breakdown",
                "billing_period": billing_period,
                "account": dimension_val,
                "breakdown": self._business_cost.get_dimension_breakdown(
                    dimension=DimensionType.ACCOUNT,
                    billing_period=billing_period,
                ),
                "analysis_type_hint": "ACCOUNT_ANALYSIS",
            }
            return ctx, analysis

        if dimension == "shared_infrastructure":
            logger.info("Routing: shared_infrastructure_analysis")
            ctx = self._business_cost.get_shared_infrastructure_analysis(billing_period=billing_period)
            if ctx:
                ctx["analysis_type_hint"] = "COMMON_INFRA_ANALYSIS"
            return ctx, analysis

        # ── Standard intent dispatch ──────────────────────────────────────

        if analysis_type == "ORGANIZATION_SUMMARY":
            logger.info("Fetching: organization_summary")
            return self._business_cost.get_organization_summary(billing_period=billing_period), analysis

        if analysis_type == "MONTH_COMPARISON":
            logger.info("Fetching: compare_months")
            period_a = comparison_periods[0] if len(comparison_periods) >= 2 else None
            period_b = comparison_periods[-1] if comparison_periods else billing_period
            return self._business_cost.compare_months(
                current_period=period_b,
                previous_period=period_a,
            ), analysis

        if analysis_type == "MONTHLY_TREND":
            logger.info("Fetching: monthly_trend")
            trend_ctx = self._business_cost.get_monthly_trend(limit=12)
            # Enrich with top_services so LLM can report top spending services
            if trend_ctx:
                top_period = billing_period or (comparison_periods[-1] if comparison_periods else None)
                top_svc_ctx = self._business_cost.get_top_services(billing_period=top_period, limit=5)
                trend_ctx["top_services"] = top_svc_ctx["top_services"] if top_svc_ctx else []
                trend_ctx["analysis_type_hint"] = "MONTHLY_TREND"
            return trend_ctx, analysis

        if analysis_type == "EXECUTIVE_SUMMARY":
            logger.info("Fetching: executive_summary for period=%s", billing_period)
            return self._business_cost.get_executive_summary(billing_period=billing_period), analysis

        if analysis_type == "BUSINESS_INSIGHTS":
            logger.info("Fetching: business_insights")
            summary = self._business_cost.get_month_summary(billing_period=billing_period)
            comparison = self._business_cost.compare_months(current_period=billing_period)
            if summary:
                summary["month_comparison"] = comparison or {}
                summary["analysis"] = "business_insights"
            return summary, analysis

        if analysis_type == "SERVICE_COMPARISON" and service_name:
            target = comparison_target or service_name
            primary = service_name
            logger.info("Fetching: service_comparison('%s', '%s')", primary, target)
            if target and target != primary:
                return self._business_cost.get_service_comparison(
                    service_a=primary,
                    service_b=target,
                    billing_period=billing_period,
                ), analysis
            return self._fetch_service_context(service_name, billing_period, comparison_periods), analysis

        if analysis_type in ("SERVICE_TREND", "SERVICE_COST", "SERVICE_BREAKDOWN", "SIMPLE_LOOKUP") and service_name:
            logger.info("Fetching: service context for '%s' (intent=%s)", service_name, analysis_type)
            return self._fetch_service_context(service_name, billing_period, comparison_periods), analysis

        if analysis_type == "COST_BREAKDOWN":
            logger.info("Fetching: cost_breakdown → month_summary")
            return self._business_cost.get_month_summary(billing_period=billing_period), analysis

        if analysis_type == "HIGHEST_SERVICE":
            logger.info("Fetching: highest_service")
            return self._business_cost.get_highest_service(billing_period=billing_period), analysis

        if analysis_type == "LOWEST_SERVICE":
            logger.info("Fetching: lowest_service")
            return self._business_cost.get_lowest_service(billing_period=billing_period), analysis

        if analysis_type == "TOP_SERVICES":
            logger.info("Fetching: top_services (limit=%s)", top_n)
            return self._business_cost.get_top_services(billing_period=billing_period, limit=top_n), analysis

        if analysis_type in ("YEAR_SUMMARY", "YEARLY_SUMMARY"):
            logger.info("Fetching: year_summary for year=%s", year)
            if year is not None:
                ctx = self._business_cost.get_year_summary(year)
            else:
                ctx = self._business_cost.get_year_summary(int(billing_period[:4])) if billing_period else None
            if ctx:
                # Enrich with top_services for the latest available month in that year
                year_periods = sorted(
                    p for p in self._cost_query.get_available_periods()
                    if p.startswith(str(ctx.get("year", year or "")))
                )
                latest_year_period = year_periods[-1] if year_periods else billing_period
                top_svc_ctx = self._business_cost.get_top_services(
                    billing_period=latest_year_period, limit=5
                )
                ctx["top_services"] = top_svc_ctx["top_services"] if top_svc_ctx else []
                ctx["latest_period"] = latest_year_period
            return ctx, analysis

        if analysis_type in ("PERCENTAGE_CONTRIBUTION", "BIGGEST_CONTRIBUTOR", "MONTHLY_AVERAGE"):
            logger.info("Fetching: month_summary for %s", analysis_type)
            if analysis_type == "MONTHLY_AVERAGE":
                return self._business_cost.get_monthly_average(), analysis
            return self._business_cost.get_month_summary(billing_period=billing_period), analysis

        if analysis_type == "COST_OPTIMIZATION":
            logger.info("Fetching: optimization_context")
            return self._business_cost.get_optimization_context(), analysis

        if analysis_type == "FORECAST":
            logger.info("Fetching: monthly_trend for forecast base")
            return self._business_cost.get_monthly_trend(limit=6), analysis

        # Default
        logger.info("Fetching: month_summary (default)")
        return self._business_cost.get_month_summary(billing_period=billing_period), analysis

    # ── Helper: service context builder ──────────────────────────────────────

    def _fetch_service_context(
        self,
        service_name: str,
        billing_period: str | None,
        comparison_periods: list[str],
    ) -> dict[str, Any] | None:
        """Build enriched service trend context from PostgreSQL history.

        When comparison_periods contains a resolved set of periods (e.g. from a
        "last 6 months" relative date query), the history is filtered to those
        exact periods so the answer covers precisely the requested time range.
        """
        from app.services.entity_resolver import resolve_canonical_service  # noqa: PLC0415
        target_business = resolve_canonical_service(service_name) or resolve_service_name_alias(service_name)
        history = self._business_cost.get_service_history(target_business)

        if history:
            # Filter history to requested periods when a specific set was provided
            if len(comparison_periods) >= 2:
                period_set = set(comparison_periods)
                history = [h for h in history if h["billing_period"] in period_set]
            elif len(comparison_periods) == 1:
                # Single specific period
                history = [h for h in history if h["billing_period"] == comparison_periods[0]]

            # If filtering left us with nothing, restore full history
            if not history:
                history = self._business_cost.get_service_history(target_business)

            highest_month = max(history, key=lambda x: x["cost"]) if history else None
            lowest_month = min(history, key=lambda x: x["cost"]) if history else None
            total_spend = sum(x["cost"] for x in history) if history else 0.0
            average_cost = total_spend / len(history) if history else 0.0

            changes: list[dict[str, Any]] = []
            for i in range(1, len(history)):
                prev = history[i - 1]["cost"]
                curr = history[i]["cost"]
                diff = curr - prev
                pct = (diff / prev * 100) if prev else 0.0
                changes.append({
                    "period_a": history[i - 1]["billing_period"],
                    "period_b": history[i]["billing_period"],
                    "difference": round(diff, 2),
                    "percentage_change": round(pct, 1),
                })

            trend_direction = "stable"
            if len(history) >= 2:
                first_cost = history[0]["cost"]
                last_cost = history[-1]["cost"]
                if last_cost > first_cost * 1.05:
                    trend_direction = "increasing"
                elif last_cost < first_cost * 0.95:
                    trend_direction = "decreasing"

            growth_rate = None
            if len(history) >= 2 and history[0]["cost"]:
                growth_rate = round(
                    (history[-1]["cost"] - history[0]["cost"]) / history[0]["cost"] * 100, 1
                )

            largest_increase = max(changes, key=lambda x: x["difference"]) if changes else None
            largest_decrease = min(changes, key=lambda x: x["difference"]) if changes else None

            opt = self._business_cost.get_optimization_context()
            service_opts: list[dict[str, Any]] = []
            if opt and "recommendations" in opt:
                for rec in opt["recommendations"]:
                    if resolve_service_name_alias(rec["service"]).lower() == target_business.lower():
                        service_opts.append(rec)

            # For SIMPLE_LOOKUP: filter to requested billing period
            current_period_cost = None
            if billing_period:
                period_record = next(
                    (h for h in history if h["billing_period"] == billing_period), None
                )
                if period_record:
                    current_period_cost = period_record["cost"]

            return {
                "analysis": "service_cost",
                "billing_period": billing_period or (history[-1]["billing_period"] if history else None),
                "service": target_business,
                "history": history,
                "total_spend": round(total_spend, 2),
                "current_period_cost": current_period_cost,
                "highest_month": highest_month,
                "lowest_month": lowest_month,
                "average_cost": round(average_cost, 2),
                "changes": changes,
                "trend_direction": trend_direction,
                "growth_rate": growth_rate,
                "largest_increase": largest_increase,
                "largest_decrease": largest_decrease,
                "optimization_suggestions": service_opts,
            }

        # No history — fall back to single-period cost
        raw_cost = self._business_cost.get_service_cost(service_name, billing_period=billing_period)
        if raw_cost:
            return raw_cost

        return None

    @staticmethod
    def _response(
        question: str,
        route: str,
        answer: str,
        explanation: str,
        sources: list[dict[str, Any]] | None = None,
        suggestions: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "question": question,
            "route": route,
            "answer": answer,
            "explanation": explanation,
            "sources": sources or [],
            "suggestions": suggestions or [],
        }
