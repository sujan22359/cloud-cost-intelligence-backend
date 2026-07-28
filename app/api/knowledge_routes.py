import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.knowledge_schema import (
    KnowledgeCreate,
    KnowledgeResponse,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
    KnowledgeUpdate,
)
from app.services.knowledge_retrieval_service import KnowledgeRetrievalService
from app.services.knowledge_service import KnowledgeService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/knowledge", tags=["AI Knowledge Base"])


def get_knowledge_service() -> KnowledgeService:
    return KnowledgeService()


def get_knowledge_retrieval_service() -> KnowledgeRetrievalService:
    return KnowledgeRetrievalService()


@router.post(
    "",
    response_model=KnowledgeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add new knowledge entry to AI Knowledge Base",
)
def create_knowledge_entry(
    payload: KnowledgeCreate,
    db: Session = Depends(get_db),
    service: KnowledgeService = Depends(get_knowledge_service),
) -> KnowledgeResponse:
    """Create a new enterprise organization knowledge entry."""
    entry = service.create_knowledge(db, payload)
    return KnowledgeResponse.model_validate(entry)


@router.get(
    "",
    response_model=List[KnowledgeResponse],
    summary="List and filter AI Knowledge Base entries",
)
def list_knowledge_entries(
    category: Optional[str] = Query(None, description="Filter by category"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    month: Optional[str] = Query(None, description="Filter by month"),
    search: Optional[str] = Query(None, description="Keyword search in title/content/tags"),
    db: Session = Depends(get_db),
    service: KnowledgeService = Depends(get_knowledge_service),
) -> List[KnowledgeResponse]:
    """Retrieve all cumulative organization knowledge base entries with optional filtering."""
    entries = service.list_knowledge(db, category=category, tag=tag, month=month, search=search)
    return [KnowledgeResponse.model_validate(e) for e in entries]


@router.get(
    "/{knowledge_id}",
    response_model=KnowledgeResponse,
    summary="Get AI Knowledge Base entry by ID",
)
def get_knowledge_entry(
    knowledge_id: int,
    db: Session = Depends(get_db),
    service: KnowledgeService = Depends(get_knowledge_service),
) -> KnowledgeResponse:
    """Get details for a single knowledge entry by ID."""
    entry = service.get_knowledge_by_id(db, knowledge_id)
    return KnowledgeResponse.model_validate(entry)


@router.put(
    "/{knowledge_id}",
    response_model=KnowledgeResponse,
    summary="Update existing AI Knowledge Base entry",
)
def update_knowledge_entry(
    knowledge_id: int,
    payload: KnowledgeUpdate,
    db: Session = Depends(get_db),
    service: KnowledgeService = Depends(get_knowledge_service),
) -> KnowledgeResponse:
    """Explicitly update a knowledge entry."""
    entry = service.update_knowledge(db, knowledge_id, payload)
    return KnowledgeResponse.model_validate(entry)


@router.delete(
    "/{knowledge_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete AI Knowledge Base entry",
)
def delete_knowledge_entry(
    knowledge_id: int,
    db: Session = Depends(get_db),
    service: KnowledgeService = Depends(get_knowledge_service),
) -> dict:
    """Explicitly delete a knowledge entry by ID."""
    service.delete_knowledge(db, knowledge_id)
    return {"success": True, "message": f"Knowledge entry {knowledge_id} deleted successfully."}


@router.post(
    "/search",
    response_model=KnowledgeSearchResponse,
    summary="Retrieve Top-N relevant AI Knowledge Base entries for a question",
)
def search_knowledge_entries(
    payload: KnowledgeSearchRequest,
    db: Session = Depends(get_db),
    retrieval_service: KnowledgeRetrievalService = Depends(get_knowledge_retrieval_service),
) -> KnowledgeSearchResponse:
    """Perform lightweight Top-N relevance retrieval on AI Knowledge Base."""
    results = retrieval_service.retrieve_relevant_knowledge(
        db,
        question=payload.query or "",
        top_n=payload.top_n,
        category=payload.category,
        month=payload.month,
        tags=payload.tags,
    )
    return KnowledgeSearchResponse(
        query=payload.query,
        total_found=len(results),
        items=[KnowledgeResponse.model_validate(e) for e in results],
    )
