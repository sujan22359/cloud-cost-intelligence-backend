import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.knowledge_models import OrganizationKnowledge
from app.exceptions import KnowledgeNotFoundError, KnowledgeValidationError
from app.schemas.knowledge_schema import KnowledgeCreate, KnowledgeUpdate
from app.services.keyword_extraction_service import KeywordExtractionService

logger = logging.getLogger(__name__)


class KnowledgeService:
    """Service layer for cumulative Organization Knowledge Base management."""

    def __init__(self, keyword_extractor: Optional[KeywordExtractionService] = None) -> None:
        self.keyword_extractor = keyword_extractor or KeywordExtractionService()

    def create_knowledge(self, db: Session, data: KnowledgeCreate) -> OrganizationKnowledge:
        """Create a new knowledge base record.

        Automatically extracts keywords from title, content, category, and month.
        Knowledge is cumulative. New records will never overwrite existing entries.
        """
        logger.info("Creating new knowledge entry: title='%s', category='%s'", data.title, data.category)
        if not data.title.strip():
            raise KnowledgeValidationError("Knowledge title cannot be empty.")
        if not data.content.strip():
            raise KnowledgeValidationError("Knowledge content cannot be empty.")

        # Automatically extract keywords
        extracted_tags = self.keyword_extractor.extract_keywords(
            title=data.title.strip(),
            content=data.content.strip(),
            category=data.category.strip(),
            month=data.month.strip() if data.month else "",
        )

        entry = OrganizationKnowledge(
            title=data.title.strip(),
            category=data.category.strip(),
            month=data.month.strip() if data.month else None,
            tags=extracted_tags,
            content=data.content.strip(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        logger.info("Successfully created knowledge record id=%d with auto-extracted tags='%s'", entry.id, extracted_tags)
        return entry

    def get_knowledge_by_id(self, db: Session, knowledge_id: int) -> OrganizationKnowledge:
        """Retrieve a specific knowledge record by ID."""
        entry = db.query(OrganizationKnowledge).filter(OrganizationKnowledge.id == knowledge_id).first()
        if not entry:
            logger.warning("Knowledge entry id=%d not found", knowledge_id)
            raise KnowledgeNotFoundError(knowledge_id)
        return entry

    def list_knowledge(
        self,
        db: Session,
        category: Optional[str] = None,
        tag: Optional[str] = None,
        month: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[OrganizationKnowledge]:
        """List and filter knowledge records ordered by newest first."""
        query = db.query(OrganizationKnowledge)

        if category:
            query = query.filter(OrganizationKnowledge.category.ilike(f"%{category.strip()}%"))

        if month:
            query = query.filter(OrganizationKnowledge.month.ilike(f"%{month.strip()}%"))

        if tag:
            query = query.filter(OrganizationKnowledge.tags.ilike(f"%{tag.strip()}%"))

        if search:
            search_term = f"%{search.strip()}%"
            query = query.filter(
                or_(
                    OrganizationKnowledge.title.ilike(search_term),
                    OrganizationKnowledge.content.ilike(search_term),
                    OrganizationKnowledge.tags.ilike(search_term),
                    OrganizationKnowledge.category.ilike(search_term),
                    OrganizationKnowledge.month.ilike(search_term),
                )
            )

        entries = query.order_by(OrganizationKnowledge.created_at.desc()).all()
        logger.info("Retrieved %d knowledge records for filters category=%s, tag=%s, search=%s", len(entries), category, tag, search)
        return entries

    def update_knowledge(self, db: Session, knowledge_id: int, data: KnowledgeUpdate) -> OrganizationKnowledge:
        """Explicitly update a knowledge entry by ID."""
        entry = self.get_knowledge_by_id(db, knowledge_id)

        if data.title is not None:
            if not data.title.strip():
                raise KnowledgeValidationError("Knowledge title cannot be empty.")
            entry.title = data.title.strip()

        if data.category is not None:
            if not data.category.strip():
                raise KnowledgeValidationError("Knowledge category cannot be empty.")
            entry.category = data.category.strip()

        if data.month is not None:
            entry.month = data.month.strip() if data.month else None

        if data.tags is not None:
            entry.tags = data.tags.strip() if data.tags else None

        if data.content is not None:
            if not data.content.strip():
                raise KnowledgeValidationError("Knowledge content cannot be empty.")
            entry.content = data.content.strip()

        # Automatically regenerate keywords during update
        entry.tags = self.keyword_extractor.extract_keywords(
            title=entry.title,
            content=entry.content,
            category=entry.category,
            month=entry.month or "",
        )

        entry.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(entry)
        logger.info("Successfully updated knowledge record id=%d with auto-extracted tags='%s'", entry.id, entry.tags)
        return entry

    def delete_knowledge(self, db: Session, knowledge_id: int) -> bool:
        """Explicitly delete a knowledge record by ID."""
        entry = self.get_knowledge_by_id(db, knowledge_id)
        db.delete(entry)
        db.commit()
        logger.info("Successfully deleted knowledge record id=%d", knowledge_id)
        return True
