from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from app.db.database import Base


class OrganizationKnowledge(Base):
    """SQLAlchemy model for enterprise organization knowledge base entries."""

    __tablename__ = "organization_knowledge"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    category = Column(String(100), nullable=False)
    month = Column(String(50), nullable=True)
    tags = Column(String(255), nullable=True)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def to_dict(self) -> dict:
        """Convert model to dictionary representation."""
        return {
            "id": self.id,
            "title": self.title,
            "category": self.category,
            "month": self.month,
            "tags": self.tags,
            "content": self.content,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
