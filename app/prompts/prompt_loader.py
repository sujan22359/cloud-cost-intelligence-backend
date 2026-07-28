"""Centralized prompt retrieval helpers for the AWS backend."""

from app.prompts.cost_prompts import (
    build_account_analysis_prompt,
    build_common_infra_prompt,
    build_comparison_prompt,
    build_cost_insights_prompt,
    build_cost_optimization_prompt,
    build_cost_summary_prompt,
    build_developer_analysis_prompt,
    build_environment_analysis_prompt,
    build_executive_summary_prompt,
    build_monthly_trend_prompt,
    build_org_summary_prompt,
    build_product_analysis_prompt,
    build_region_analysis_prompt,
    build_service_comparison_prompt,
    build_service_trend_prompt,
    build_simple_lookup_prompt,
    build_top_n_prompt,
    get_prompt_for_intent,
)
from app.prompts.intent_prompts import build_intent_classifier_prompt
from app.prompts.system_prompts import (
    COST_OPTIMIZATION_SYSTEM_PROMPT,
    COST_SYSTEM_PROMPT,
    ENTERPRISE_FINOPS_SYSTEM_PROMPT,
    EXECUTIVE_SUMMARY_SYSTEM_PROMPT,
    GENERAL_ASSISTANT_SYSTEM_PROMPT,
    SIMPLE_LOOKUP_SYSTEM_PROMPT,
)

# ── System prompt getters ────────────────────────────────────────────────────

def get_cost_system_prompt() -> str:
    return ENTERPRISE_FINOPS_SYSTEM_PROMPT


def get_cost_optimization_system_prompt() -> str:
    return COST_OPTIMIZATION_SYSTEM_PROMPT


def get_executive_summary_system_prompt() -> str:
    return EXECUTIVE_SUMMARY_SYSTEM_PROMPT


def get_simple_lookup_system_prompt() -> str:
    return SIMPLE_LOOKUP_SYSTEM_PROMPT


def get_general_system_prompt() -> str:
    return GENERAL_ASSISTANT_SYSTEM_PROMPT


# ── Prompt builder getters (direct function references for zero-overhead) ──

get_cost_insights_prompt = build_cost_insights_prompt
get_cost_summary_prompt = build_cost_summary_prompt
get_simple_lookup_prompt = build_simple_lookup_prompt
get_cost_optimization_prompt = build_cost_optimization_prompt
get_service_trend_prompt = build_service_trend_prompt
get_monthly_trend_prompt = build_monthly_trend_prompt
get_executive_summary_prompt = build_executive_summary_prompt
get_service_comparison_prompt = build_service_comparison_prompt
get_comparison_prompt = build_comparison_prompt
get_product_analysis_prompt = build_product_analysis_prompt
get_environment_analysis_prompt = build_environment_analysis_prompt
get_region_analysis_prompt = build_region_analysis_prompt
get_account_analysis_prompt = build_account_analysis_prompt
get_top_n_prompt = build_top_n_prompt
get_common_infra_prompt = build_common_infra_prompt
get_org_summary_prompt = build_org_summary_prompt
get_developer_analysis_prompt = build_developer_analysis_prompt


def get_prompt_by_intent(analysis_type: str, question: str, payload: str) -> str:
    """Dispatch to the correct prompt by analysis_type."""
    return get_prompt_for_intent(analysis_type, question, payload)


def get_intent_prompt(question: str) -> str:
    return build_intent_classifier_prompt(question)
