"""Question-answering endpoints for the AWS Cost Intelligence Assistant."""

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, status

from app.routing import QuestionRouter
from app.schemas.rag_schema import AskRequest, AskResponse
from app.services.business_cost_service import BusinessCostService
from app.services.bedrock_service import BedrockService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Assistant"])


# ── Dependency factories ──────────────────────────────────────────────────────

def get_llm_service() -> BedrockService:
    return BedrockService()


def get_business_cost_service() -> BusinessCostService:
    return BusinessCostService()


async def _run_sync(func, *args) -> any:
    return await asyncio.get_running_loop().run_in_executor(None, func, *args)


@router.post(
    "/ask",
    response_model=AskResponse,
    summary="Ask a Cost Explorer question backed by PostgreSQL",
)
async def ask(
    request: AskRequest,
    business_cost_service: BusinessCostService = Depends(get_business_cost_service),
    llm_service: BedrockService = Depends(get_llm_service),
) -> AskResponse:
    """Route the question to PostgreSQL-backed cost data only."""
    question_router = QuestionRouter(llm_service, business_cost_service=business_cost_service)
    try:
        result = await _run_sync(
            question_router.answer,
            request.question,
            request.top_k,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    result.setdefault("model_used", llm_service.model_id)
    return AskResponse(**result)
