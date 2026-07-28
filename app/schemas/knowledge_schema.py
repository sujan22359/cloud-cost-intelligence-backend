from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class KnowledgeCategory(str, Enum):
    MONTHLY_REVIEW = "Monthly Review"
    INFRASTRUCTURE_CHANGE = "Infrastructure Change"
    ARCHITECTURE_DECISION = "Architecture Decision"
    COST_OPTIMIZATION = "Cost Optimization"
    BUSINESS_UPDATE = "Business Update"
    GENERAL_KNOWLEDGE = "General Knowledge"


class KnowledgeBaseModel(BaseModel):
    title: str = Field(..., min_length=1, max_length=255, description="Title of the knowledge entry")
    category: str = Field(..., description="Category of the knowledge entry")
    month: Optional[str] = Field(None, max_length=50, description="Optional target month e.g. June 2026")
    tags: Optional[str] = Field(None, max_length=255, description="Optional comma-separated tags")
    content: str = Field(..., min_length=1, description="Knowledge content body")


class KnowledgeCreate(KnowledgeBaseModel):
    pass


class KnowledgeUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    category: Optional[str] = Field(None)
    month: Optional[str] = Field(None, max_length=50)
    tags: Optional[str] = Field(None, max_length=255)
    content: Optional[str] = Field(None, min_length=1)


class KnowledgeResponse(KnowledgeBaseModel):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class KnowledgeSearchRequest(BaseModel):
    query: Optional[str] = Field(None, description="Search query or user question")
    category: Optional[str] = Field(None, description="Filter by category")
    month: Optional[str] = Field(None, description="Filter by month")
    tags: Optional[List[str]] = Field(None, description="Filter by tag list")
    top_n: int = Field(default=3, ge=1, le=20, description="Number of top relevant results to retrieve")


class KnowledgeSearchResponse(BaseModel):
    query: Optional[str]
    total_found: int
    items: List[KnowledgeResponse]
