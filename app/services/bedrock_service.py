"""Reusable Amazon Bedrock Claude 3 Haiku service."""

import json
import logging
from typing import Any

from botocore.exceptions import BotoCoreError, ClientError

from app.config import get_settings
from app.prompts.intent_prompts import INTENT_CLASSIFIER_SYSTEM_PROMPT
from app.prompts.prompt_loader import (
    get_cost_insights_prompt,
    get_cost_optimization_prompt,
    get_cost_optimization_system_prompt,
    get_executive_summary_prompt,
    get_general_system_prompt,
    get_intent_prompt,
    get_service_comparison_prompt,
    get_service_trend_prompt,
)
from app.prompts.system_prompts import COST_SYSTEM_PROMPT
from app.utils.aws_utils import get_bedrock_client

logger = logging.getLogger(__name__)
settings = get_settings()


class BedrockService:
    """Generate answers using Claude 3 Haiku / Claude 3.5 Haiku on Amazon Bedrock."""

    def __init__(self) -> None:
        self._client = get_bedrock_client(region=settings.bedrock_region)
        self._model_id = settings.bedrock_model_id

    @property
    def model_id(self) -> str:
        return self._model_id

    def generate_response(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float | None = None,
    ) -> str:
        """Generate a text response from Claude 3 Haiku."""
        system_prompt = system_prompt or get_general_system_prompt()
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": settings.bedrock_max_tokens,
            "temperature": settings.bedrock_temperature if temperature is None else temperature,
            "system": system_prompt,
            "messages": [{"role": "user", "content": prompt}],
        }
        try:
            logger.info("LLM Request: Bedrock model=%s", self._model_id)
            response = self._client.invoke_model(
                modelId=self._model_id,
                contentType="application/json",
                accept="application/json",
                body=json.dumps(body),
            )
        except (ClientError, BotoCoreError) as exc:
            raise RuntimeError(f"Bedrock error: {exc}") from exc

        payload = json.loads(response["body"].read())
        text = payload.get("content", [{}])[0].get("text", "")
        logger.info("LLM Response: Bedrock chars=%d", len(text))
        return text

    def classify_intent(self, question: str) -> str:
        """Classify the question into the cost route.

        Returns only one word.
        """
        logger.info("LLM Request: Bedrock intent classification")
        response = self.generate_response(
            prompt=get_intent_prompt(question),
            system_prompt=INTENT_CLASSIFIER_SYSTEM_PROMPT,
            temperature=0.0,
        )
        intent = response.strip().split()[0].lower() if response.strip() else "cost"
        result = intent if intent == "cost" else "cost"
        logger.info("LLM Response: Bedrock intent=%s", result)
        return result

    def _parse_answer_and_explanation(self, response: str) -> tuple[str, str]:
        """Parse response into answer and explanation robustly."""
        lines = response.strip().split('\n')
        answer_lines = []
        explanation_lines = []
        current_section = None

        for line in lines:
            line_strip = line.strip()
            line_upper = line_strip.upper()
            if line_upper.startswith("ANSWER:") or line_upper.startswith("**ANSWER:**") or line_upper.startswith("### ANSWER"):
                current_section = "answer"
                cleaned = line_strip
                for prefix in ["ANSWER:", "**ANSWER:**", "### ANSWER", "Answer:", "**Answer:**"]:
                    if cleaned.startswith(prefix):
                        cleaned = cleaned[len(prefix):].strip()
                if cleaned:
                    answer_lines.append(cleaned)
            elif line_upper.startswith("EXPLANATION:") or line_upper.startswith("**EXPLANATION:**") or line_upper.startswith("### EXPLANATION"):
                current_section = "explanation"
                cleaned = line_strip
                for prefix in ["EXPLANATION:", "**EXPLANATION:**", "### EXPLANATION", "Explanation:", "**Explanation:**"]:
                    if cleaned.startswith(prefix):
                        cleaned = cleaned[len(prefix):].strip()
                if cleaned:
                    explanation_lines.append(cleaned)
            elif current_section == "answer":
                answer_lines.append(line_strip)
            elif current_section == "explanation":
                explanation_lines.append(line_strip)
            else:
                if line_strip:
                    current_section = "answer"
                    answer_lines.append(line_strip)

        ans_str = "\n".join(answer_lines).strip()
        exp_str = "\n".join(explanation_lines).strip()
        
        if ans_str and not exp_str:
            lower_ans = ans_str.lower()
            if "explanation:" in lower_ans:
                idx = lower_ans.find("explanation:")
                exp_str = ans_str[idx + len("explanation:"):].strip()
                ans_str = ans_str[:idx].strip()
        
        return ans_str, exp_str

    def generate_cost_insights(self, question: str, context: dict[str, Any]) -> tuple[str, str]:
        """Answer a cost question using structured PostgreSQL cost context.

        Dispatches to a specialized prompt template based on the context analysis type
        for SERVICE_TREND, EXECUTIVE_SUMMARY, and SERVICE_COMPARISON intents.
        """
        analysis_type = context.get("analysis", "")
        payload = json.dumps(context, indent=2)

        if analysis_type == "service_cost" and context.get("history"):
            prompt = get_service_trend_prompt(question, payload)
        elif analysis_type == "executive_summary":
            prompt = get_executive_summary_prompt(question, payload)
        elif analysis_type == "service_comparison":
            prompt = get_service_comparison_prompt(question, payload)
        else:
            prompt = get_cost_insights_prompt(question, payload)

        response = self.generate_response(
            prompt=prompt,
            system_prompt=COST_SYSTEM_PROMPT,
        )
        return self._parse_answer_and_explanation(response)

    def generate_intent_answer(
        self,
        question: str,
        context: dict[str, Any],
        analysis_type: str,
    ) -> tuple[str, str]:
        """Select the per-intent prompt and generate an answer.

        This is the primary entry point for the Enterprise FinOps Copilot.
        Selects prompt depth and system prompt based on the classified intent.
        """
        from app.prompts.cost_prompts import get_prompt_for_intent  # noqa: PLC0415
        from app.prompts.system_prompts import (  # noqa: PLC0415
            ENTERPRISE_FINOPS_SYSTEM_PROMPT,
            SIMPLE_LOOKUP_SYSTEM_PROMPT,
            COST_OPTIMIZATION_SYSTEM_PROMPT,
            EXECUTIVE_SUMMARY_SYSTEM_PROMPT,
        )

        payload = json.dumps(context, indent=2)

        # Use hint from router if available (overrides raw analysis type)
        effective_type = context.get("analysis_type_hint") or analysis_type

        # Select system prompt by intent depth
        if effective_type in ("SIMPLE_LOOKUP", "SERVICE_COST", "HIGHEST_SERVICE",
                               "LOWEST_SERVICE", "TOP_SERVICES"):
            system_prompt = SIMPLE_LOOKUP_SYSTEM_PROMPT
            temperature = 0.1
        elif effective_type == "COST_OPTIMIZATION":
            system_prompt = COST_OPTIMIZATION_SYSTEM_PROMPT
            temperature = 0.2
        elif effective_type in ("EXECUTIVE_SUMMARY", "ORGANIZATION_SUMMARY",
                                 "BUSINESS_INSIGHTS", "YEAR_SUMMARY"):
            system_prompt = EXECUTIVE_SUMMARY_SYSTEM_PROMPT
            temperature = 0.35
        else:
            system_prompt = ENTERPRISE_FINOPS_SYSTEM_PROMPT
            temperature = 0.3

        ai_knowledge = context.get("ai_knowledge")
        cost_data_note = context.get("cost_data_note")

        if ai_knowledge or cost_data_note:
            if cost_data_note:
                cost_payload = f"Note: {cost_data_note}"
            else:
                ctx_cost_only = {k: v for k, v in context.items() if k != "ai_knowledge"}
                cost_payload = json.dumps(ctx_cost_only, indent=2)

            if ai_knowledge:
                knowledge_lines = []
                for item in ai_knowledge:
                    t = item.get("title", "Untitled")
                    cat = item.get("category", "General Knowledge")
                    m = f" (Month: {item['month']})" if item.get("month") else ""
                    tags = f" (Tags: {item['tags']})" if item.get("tags") else ""
                    c = item.get("content", "")
                    knowledge_lines.append(f"Title: {t}\nCategory: {cat}{m}{tags}\nContent:\n{c}")
                knowledge_text = "\n\n".join(knowledge_lines)
            else:
                knowledge_text = "No matching organizational knowledge records were found for this query."

            prompt = (
                "====================================\n"
                "AWS COST DATA\n"
                "====================================\n"
                f"{cost_payload}\n\n"
                "====================================\n"
                "AI KNOWLEDGE\n"
                "====================================\n"
                f"{knowledge_text}\n\n"
                "====================================\n"
                "USER QUESTION\n"
                "====================================\n"
                f"{question}"
            )
        else:
            prompt = get_prompt_for_intent(effective_type, question, payload)

        logger.info("LLM Request: Bedrock intent=%s temperature=%.2f", effective_type, temperature)
        response = self.generate_response(
            prompt=prompt,
            system_prompt=system_prompt,
            temperature=temperature,
        )
        return self._parse_answer_and_explanation(response)

    def generate_optimization_answer(
        self,
        question: str,
        context: dict[str, Any],
    ) -> tuple[str, str]:
        """Answer a cost optimization question using structured PostgreSQL context."""
        payload = json.dumps(context, indent=2)
        prompt = get_cost_optimization_prompt(question, payload)
        response = self.generate_response(
            prompt=prompt,
            system_prompt=get_cost_optimization_system_prompt(),
            temperature=0.2,
        )
        return self._parse_answer_and_explanation(response)

    def generate_invoice_answer(self, question: str, chunks: list[dict[str, Any]]) -> tuple[str, str]:
        raise NotImplementedError("Invoice QA has been removed from this service.")
