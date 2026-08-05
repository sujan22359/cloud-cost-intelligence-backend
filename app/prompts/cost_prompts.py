"""Enterprise FinOps Copilot — Intent-specific prompt templates.

Refactored for Claude 3.5 / 4.5 token efficiency and reusable template architecture.
All business logic, output structures, builder signatures, and aliases are preserved.
"""

from __future__ import annotations

from typing import Callable

# ── Base Context Header ────────────────────────────────────────────────────────

_BASE_PROMPT = """Context:
{payload}

Question: {question}
"""

# ── Generic Dimension Analysis Builder ────────────────────────────────────────

def _build_generic_analysis_prompt(
    dimension_title: str,
    payload: str,
    question: str,
    scope_note: str = "",
    breakdown_label: str = "Top Services",
) -> str:
    note_clause = f"\nNote: {scope_note}\n" if scope_note else ""
    return (
        f"Analyze spending for the specified {dimension_title.lower()}.\n"
        f"{note_clause}\n"
        f"Context:\n{payload}\n\n"
        f"Question: {question}\n\n"
        "Respond using ONLY these plain section labels:\n\n"
        f"{dimension_title} — [Entity Name]\n"
        "[Total spend for this entity in the specified period]\n\n"
        f"{breakdown_label}\n"
        "• [Item]: $X,XXX.XX (X.X%)\n"
        "[List top contributing services or sub-items]\n\n"
        "Key Observations\n"
        "[2-3 bullet points on notable cost patterns]\n\n"
        "Business Interpretation\n"
        "[1-2 sentences on spending drivers]"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. SIMPLE LOOKUP
# ─────────────────────────────────────────────────────────────────────────────

SIMPLE_LOOKUP_PROMPT = """Answer with ONE direct sentence only.

Context:
{payload}

Question: {question}

Example format:
'Video Processing (AWS Elemental MediaConvert) cost in June 2026: **$1,234.56**'

Do not add context, recommendations, or extra lines.
"""

# ─────────────────────────────────────────────────────────────────────────────
# 2. COST SUMMARY
# ─────────────────────────────────────────────────────────────────────────────

COST_SUMMARY_PROMPT = """Provide a structured cost summary.

Context:
{payload}

Question: {question}

Respond using ONLY these plain section labels:

Cost Summary
• Analysis Period: [Start Month YYYY] → [End Month YYYY]
• Latest Cost: $X,XXX.XX
• Trend: [Increasing / Decreasing / Stable]
• Overall Change: [Percentage change compared to start, e.g. +X.X% or -X.X%]

Top Services
[For each service in top 5, list as a bullet point with friendly service name first, then cost, and percentage share if multiple services exist]

Key Observation
[One sentence describing the most notable cost pattern]
"""

# ─────────────────────────────────────────────────────────────────────────────
# 3. MONTHLY TREND
# ─────────────────────────────────────────────────────────────────────────────

MONTHLY_TREND_PROMPT = """Analyze the monthly spending trend.

Context:
{payload}

Question: {question}

Respond using ONLY these plain section labels:

Trend Overview
• Analysis Period: [Start Month YYYY] → [End Month YYYY]
• Trend Direction: [Increasing / Decreasing / Stable]

Monthly Breakdown
[Format as an ordered list of months with costs, e.g.:
1. [Month YYYY]: $X,XXX.XX
2. [Month YYYY]: $X,XXX.XX]

Key Observations
• Highest month: [Month YYYY — $X,XXX.XX]
• Lowest month: [Month YYYY — $X,XXX.XX]
• Overall trend: [Increasing / Decreasing / Stable]

Business Interpretation
[1-2 sentences on what is driving the trend]
"""

# ─────────────────────────────────────────────────────────────────────────────
# 4. SERVICE TREND
# ─────────────────────────────────────────────────────────────────────────────

SERVICE_TREND_PROMPT = """Analyze the cost trend for the requested service.

Context:
{payload}

Question: {question}

Respond using ONLY these plain section labels:

Service Trend — [Service Name]
[1 sentence: overall trajectory]

Monthly Breakdown
[List each month with cost, chronologically]

Key Observations
• Peak month: [Month YYYY — $X,XXX.XX]
• Lowest month: [Month YYYY — $X,XXX.XX]
• Average monthly spend: $X,XXX.XX
• Trend direction: [Increasing / Decreasing / Stable — X.X% overall]

Business Interpretation
[What is driving this trend? Any notable spike or drop?]
"""

# ─────────────────────────────────────────────────────────────────────────────
# 5. EXECUTIVE SUMMARY
# ─────────────────────────────────────────────────────────────────────────────

EXECUTIVE_SUMMARY_PROMPT = """Prepare a C-suite executive briefing.

Context:
{payload}

Question: {question}

Respond using ONLY these plain section labels:

Executive Summary
[Total spend for the period and the single most important observation in 1-2 sentences]

Key Findings
• Total spend: $X,XXX.XX for [Month YYYY]
• Change compared to previous period: [+/- $X,XXX.XX (+/- X.X%)]
• Largest cost driver: [Service — $X,XXX.XX (X.X% of total)]
• Largest increase: [Service — +$X,XXX.XX (+X.X%)]
• Largest decrease: [Service — -$X,XXX.XX (-X.X%)]

Top Services
[Ranked list of top 5 services with cost and percentage share]

Business Interpretation
[2-3 sentences: what this spending pattern means for the business]

Strategic Recommendation
[ONE clear, high-priority action the business should take based on the data]
"""

# ─────────────────────────────────────────────────────────────────────────────
# 6. COMPARISON
# ─────────────────────────────────────────────────────────────────────────────

COMPARISON_PROMPT = """Compare the two items using the structured data.

Context:
{payload}

Question: {question}

Respond using ONLY these plain section labels:

Comparison Summary
[Which item costs more and by how much — 1 sentence]

Side-by-Side Comparison
[Item A]: $X,XXX.XX
[Item B]: $X,XXX.XX
Difference: $X,XXX.XX (Item A is X.X% [higher/lower] than Item B)

Key Observations
[2-3 bullet points on notable differences]

Recommendation
[One clear action based on the cost comparison]
"""

# ─────────────────────────────────────────────────────────────────────────────
# 7. COST OPTIMIZATION
# ─────────────────────────────────────────────────────────────────────────────

COST_OPTIMIZATION_PROMPT = """Identify cost reduction opportunities from the data.

Context:
{payload}

Question: {question}

Respond using ONLY these plain section labels:

Top Optimization Opportunities
• [Service / Business Name (AWS Name)]: Est. savings of $X,XXX — [Specific actionable recommendation]
• [Continue for top 3-5 opportunities]

Business Impact
[Total estimated savings potential and prioritization rationale]

Next Steps
• [Concrete action 1]
• [Concrete action 2]
• [Concrete action 3]
"""

# ─────────────────────────────────────────────────────────────────────────────
# 8. TOP RANKED PROMPTS
# ─────────────────────────────────────────────────────────────────────────────

TOP_SERVICES_PROMPT = """Return the requested ranked list of top services.

Context:
{payload}

Question: {question}

Respond using ONLY these plain section labels:

Ranked Services Spend
[Rank]. [Business Service Name (AWS Name)]: **$X,XXX.XX** (X.X% of total spend)
[Continue for each service requested/top services]

Period: [Month YYYY]
"""

TOP_ACCOUNTS_PROMPT = """Return the requested ranked list of top AWS accounts.

Context:
{payload}

Question: {question}

Important: Display ONLY the human-readable Account Name (e.g. 'Gayanthika Shankar', 'SafeStart QA', 'AccuTrain Production'). NEVER display numeric Account IDs.

Respond using ONLY these plain section labels:

Ranked Accounts Spend
[Rank]. [Account Name]: **$X,XXX.XX** (X.X% of total spend)
[Continue for each account requested/top accounts]

Period: [Month YYYY]
"""

TOP_REGIONS_PROMPT = """Return the requested ranked list of top AWS regions.

Context:
{payload}

Question: {question}

Important:
- If the question asks for services by region or regional service cost breakdown, list the specific top services driving cost in each region from region_services in context (e.g. 'Canada (Central) - $183.49: Amazon RDS ($120.00), Amazon S3 ($63.49)').
- If the question asks for account details or account names by region, list the specific associated Account Names from region_accounts in context (e.g. 'Associated Accounts: SafeStart QA ($183.49)').
- Do NOT state that service-level or account-level breakdown by region is unavailable. Always use the data provided in region_services and region_accounts.

Respond using ONLY these plain section labels:

Ranked Regions Spend
[Rank]. [AWS Region Name (Friendly Name)] - **$X,XXX.XX** (X.X% of total spend)
[List Associated Accounts OR Associated Services from context for this region]
[Continue for each region requested/top regions]

Period: [Month YYYY]
"""

# ─────────────────────────────────────────────────────────────────────────────
# 9. COMMON INFRASTRUCTURE & ORGANIZATION SUMMARY
# ─────────────────────────────────────────────────────────────────────────────

COMMON_INFRA_PROMPT = """Analyze the Common Infrastructure accounts spending.

Context:
{payload}

Question: {question}

Important: Common Infrastructure accounts are: Logs, Audit, Data Platform, Sandbox.
These are organization-wide shared accounts — NOT products or environments.

Respond using ONLY these plain section labels:

Common Infrastructure Analysis
[Total spend across all infrastructure accounts for the period]

Account Breakdown
• Logs: $X,XXX.XX (X.X%) — Centralized logging
• Audit: $X,XXX.XX (X.X%) — Security and compliance
• Data Platform: $X,XXX.XX (X.X%) — Shared data services
• Sandbox: $X,XXX.XX (X.X%) — Shared experimentation

Key Observations
[2-3 bullet points on infrastructure spending patterns]

Business Interpretation
[1-2 sentences on what this infrastructure spend represents for the organization]
"""

ORG_SUMMARY_PROMPT = """Provide a complete organization-wide spending summary.

Context:
{payload}

Question: {question}

Respond using ONLY these plain section labels:

Organization Spending Summary — [Month YYYY]
[Grand total spend for the organization in one sentence]

Business Unit Breakdown
• SafeStart: $X,XXX.XX (X.X% of total)
• AccuTrain: $X,XXX.XX (X.X% of total)
• Common Infrastructure: $X,XXX.XX (X.X% of total)
  - Logs: $X,XXX.XX
  - Audit: $X,XXX.XX
  - Data Platform: $X,XXX.XX
  - Sandbox: $X,XXX.XX
Total Company Spend: $X,XXX.XX

Key Observations
[2-3 bullet points on the most significant cost patterns across the organization]

Business Interpretation
[1-2 sentences on overall organizational cost posture]
"""

MULTI_PART_COMPOUND_PROMPT = """Answer a multi-part business question.

Context:
{payload}

Question: {question}

Respond using ONLY these plain section labels in order:

Executive Summary
[1-2 direct summary sentences answering the overall compound question]

Monthly Cost Breakdown
[List monthly spending breakdown for requested service/dimension]

Trend Analysis
[Describe the directional trajectory, peak, and lowest months]

Savings Analysis
[Specific savings achieved or optimization opportunities available from the data]

Business Insight
[1-2 executive business insights explaining cost drivers]

Recommended Next Steps
[1-2 actionable, data-backed FinOps recommendations]
"""


# ─────────────────────────────────────────────────────────────────────────────
# Builder functions
# ─────────────────────────────────────────────────────────────────────────────

def build_simple_lookup_prompt(question: str, payload: str) -> str:
    return SIMPLE_LOOKUP_PROMPT.format(payload=payload, question=question)


def build_cost_summary_prompt(question: str, payload: str) -> str:
    return COST_SUMMARY_PROMPT.format(payload=payload, question=question)


def build_monthly_trend_prompt(question: str, payload: str) -> str:
    return MONTHLY_TREND_PROMPT.format(payload=payload, question=question)


def build_service_trend_prompt(question: str, payload: str) -> str:
    return SERVICE_TREND_PROMPT.format(payload=payload, question=question)


def build_executive_summary_prompt(question: str, payload: str) -> str:
    return EXECUTIVE_SUMMARY_PROMPT.format(payload=payload, question=question)


def build_product_analysis_prompt(question: str, payload: str) -> str:
    return _build_generic_analysis_prompt(
        dimension_title="Product Analysis",
        payload=payload,
        question=question,
        scope_note="Only analyze specified products (SafeStart/AccuTrain). Never include environments or common infrastructure.",
        breakdown_label="Service Breakdown",
    )


def build_environment_analysis_prompt(question: str, payload: str) -> str:
    return _build_generic_analysis_prompt(
        dimension_title="Environment Analysis",
        payload=payload,
        question=question,
        scope_note="Only analyze specified environment (QA/UAT/Development/Production).",
        breakdown_label="Top Services",
    )


def build_region_analysis_prompt(question: str, payload: str) -> str:
    return _build_generic_analysis_prompt(
        dimension_title="Region Analysis",
        payload=payload,
        question=question,
        breakdown_label="Regional Breakdown",
    )


def build_account_analysis_prompt(question: str, payload: str) -> str:
    return _build_generic_analysis_prompt(
        dimension_title="Account Analysis",
        payload=payload,
        question=question,
        breakdown_label="Top Services",
    )


def build_developer_analysis_prompt(question: str, payload: str) -> str:
    return _build_generic_analysis_prompt(
        dimension_title="Developer Account Analysis",
        payload=payload,
        question=question,
        scope_note="Analyze ONLY developer accounts (Employee and Trainee).",
        breakdown_label="Developer Breakdown",
    )


def build_comparison_prompt(question: str, payload: str) -> str:
    return COMPARISON_PROMPT.format(payload=payload, question=question)


def build_cost_optimization_prompt(question: str, payload: str) -> str:
    return COST_OPTIMIZATION_PROMPT.format(payload=payload, question=question)


def build_top_services_prompt(question: str, payload: str) -> str:
    return TOP_SERVICES_PROMPT.format(payload=payload, question=question)


def build_top_accounts_prompt(question: str, payload: str) -> str:
    return TOP_ACCOUNTS_PROMPT.format(payload=payload, question=question)


def build_top_regions_prompt(question: str, payload: str) -> str:
    return TOP_REGIONS_PROMPT.format(payload=payload, question=question)


def build_common_infra_prompt(question: str, payload: str) -> str:
    return COMMON_INFRA_PROMPT.format(payload=payload, question=question)


def build_org_summary_prompt(question: str, payload: str) -> str:
    return ORG_SUMMARY_PROMPT.format(payload=payload, question=question)


def build_multi_part_compound_prompt(question: str, payload: str) -> str:
    return MULTI_PART_COMPOUND_PROMPT.format(payload=payload, question=question)


# ── Backward-compatible aliases ───────────────────────────────────────────────

PRODUCT_ANALYSIS_PROMPT = "Product Analysis Template"
ENVIRONMENT_ANALYSIS_PROMPT = "Environment Analysis Template"
REGION_ANALYSIS_PROMPT = "Region Analysis Template"
ACCOUNT_ANALYSIS_PROMPT = "Account Analysis Template"
DEVELOPER_ANALYSIS_PROMPT = "Developer Analysis Template"

COST_INSIGHTS_PROMPT_TEMPLATE = COST_SUMMARY_PROMPT
COST_OPTIMIZATION_INSIGHTS_PROMPT = COST_OPTIMIZATION_PROMPT
COST_SERVICE_TREND_PROMPT = SERVICE_TREND_PROMPT
COST_EXECUTIVE_SUMMARY_PROMPT = EXECUTIVE_SUMMARY_PROMPT
COST_SERVICE_COMPARISON_PROMPT = COMPARISON_PROMPT
COST_SUMMARY_PROMPT_ALIAS = COST_SUMMARY_PROMPT
COST_TREND_EXPLANATION_PROMPT = MONTHLY_TREND_PROMPT
COST_COMPARISON_PROMPT = COMPARISON_PROMPT
COST_BUSINESS_EXPLANATION_PROMPT = "Provide a concise business explanation using the provided cost context."


def build_cost_insights_prompt(question: str, payload: str) -> str:
    return build_cost_summary_prompt(question, payload)


def build_service_comparison_prompt(question: str, payload: str) -> str:
    return build_comparison_prompt(question, payload)


def build_top_n_prompt(question: str, payload: str) -> str:
    return build_top_services_prompt(question, payload)


# ── Intent → prompt builder dispatch map ─────────────────────────────────────

INTENT_PROMPT_MAP: dict[str, Callable[[str, str], str]] = {
    "SIMPLE_LOOKUP": build_simple_lookup_prompt,
    "MONTH_SUMMARY": build_cost_summary_prompt,
    "COST_BREAKDOWN": build_cost_summary_prompt,
    "GENERAL_COST_QUERY": build_cost_summary_prompt,
    "PERCENTAGE_CONTRIBUTION": build_cost_summary_prompt,
    "BIGGEST_CONTRIBUTOR": build_cost_summary_prompt,
    "MONTHLY_AVERAGE": build_cost_summary_prompt,
    "MONTHLY_TREND": build_monthly_trend_prompt,
    "SERVICE_TREND": build_service_trend_prompt,
    "HISTORICAL_ANALYSIS": build_service_trend_prompt,
    "SAVINGS_ANALYSIS": build_cost_optimization_prompt,
    "COMPARISON": build_comparison_prompt,
    "MULTI_PART_COMPOUND": build_multi_part_compound_prompt,
    "FORECAST": build_monthly_trend_prompt,
    "EXECUTIVE_SUMMARY": build_executive_summary_prompt,
    "YEAR_SUMMARY": build_executive_summary_prompt,
    "BUSINESS_INSIGHTS": build_executive_summary_prompt,
    "PRODUCT_ANALYSIS": build_product_analysis_prompt,
    "ENVIRONMENT_ANALYSIS": build_environment_analysis_prompt,
    "REGION_ANALYSIS": build_top_regions_prompt,
    "ACCOUNT_ANALYSIS": build_top_accounts_prompt,
    "TOP_ACCOUNTS": build_top_accounts_prompt,
    "TOP_REGIONS": build_top_regions_prompt,
    "SERVICE_COST": build_simple_lookup_prompt,
    "HIGHEST_SERVICE": build_top_services_prompt,
    "LOWEST_SERVICE": build_top_services_prompt,
    "TOP_SERVICES": build_top_services_prompt,
    "MONTH_COMPARISON": build_comparison_prompt,
    "SERVICE_COMPARISON": build_comparison_prompt,
    "COST_OPTIMIZATION": build_cost_optimization_prompt,
    "COMMON_INFRA_ANALYSIS": build_common_infra_prompt,
    "ORGANIZATION_SUMMARY": build_org_summary_prompt,
    "DEVELOPER_ANALYSIS": build_developer_analysis_prompt,
}


def get_prompt_for_intent(analysis_type: str, question: str, payload: str) -> str:
    """Dispatch to the correct prompt builder based on analysis_type.

    Falls back to cost_summary_prompt for unknown types.
    """
    builder = INTENT_PROMPT_MAP.get(analysis_type, build_cost_summary_prompt)
    return builder(question, payload)
