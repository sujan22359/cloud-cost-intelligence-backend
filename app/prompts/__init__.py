"""Prompt organization helpers for the Bedrock backend."""

from app.prompts.cost_prompts import COST_INSIGHTS_PROMPT_TEMPLATE, build_cost_insights_prompt
from app.prompts.intent_prompts import (
    INTENT_CLASSIFIER_SYSTEM_PROMPT,
    QUESTION_CLASSIFICATION_PROMPT,
    ROUTE_SELECTION_PROMPT,
    build_intent_classifier_prompt,
)
from app.prompts.prompt_loader import (
    get_cost_insights_prompt,
    get_cost_system_prompt,
    get_general_system_prompt,
    get_intent_prompt,
)
from app.prompts.system_prompts import (
    BUSINESS_EXPLANATION_PROMPT,
    COST_SYSTEM_PROMPT,
    GENERAL_ASSISTANT_SYSTEM_PROMPT,
)

__all__ = [
    "BUSINESS_EXPLANATION_PROMPT",
    "COST_INSIGHTS_PROMPT_TEMPLATE",
    "COST_SYSTEM_PROMPT",
    "GENERAL_ASSISTANT_SYSTEM_PROMPT",
    "INTENT_CLASSIFIER_SYSTEM_PROMPT",
    "QUESTION_CLASSIFICATION_PROMPT",
    "ROUTE_SELECTION_PROMPT",
    "build_cost_insights_prompt",
    "build_intent_classifier_prompt",
    "get_cost_insights_prompt",
    "get_cost_system_prompt",
    "get_general_system_prompt",
    "get_intent_prompt",
]
