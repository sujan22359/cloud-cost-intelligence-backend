import logging
import re
from typing import List, Optional, Tuple
from datetime import datetime
from sqlalchemy.orm import Session

from app.db.knowledge_models import OrganizationKnowledge

logger = logging.getLogger(__name__)

# Stopwords to filter out from general keyword token matching
STOP_WORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are", "aren't",
    "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but", "by",
    "can", "could", "did", "do", "does", "doing", "down", "during", "each", "few", "for", "from", "further",
    "had", "has", "have", "having", "he", "her", "here", "hers", "herself", "him", "himself", "his", "how",
    "i", "if", "in", "into", "is", "it", "its", "itself", "just", "me", "more", "most", "my", "myself",
    "no", "nor", "not", "now", "of", "off", "on", "once", "only", "or", "other", "our", "ours", "ourselves",
    "out", "over", "own", "s", "same", "she", "should", "so", "some", "such", "than", "that", "the", "their",
    "theirs", "them", "themselves", "then", "there", "these", "they", "this", "those", "through", "to", "too",
    "under", "until", "up", "very", "was", "we", "were", "what", "when", "where", "which", "while", "who",
    "whom", "why", "with", "would", "you", "your", "yours", "yourself", "yourselves"
}


def tokenize(text: str) -> List[str]:
    """Tokenize text into lower-case alphanumeric tokens."""
    if not text:
        return []
    words = re.findall(r"\b[a-zA-Z0-9_-]+\b", text.lower())
    return [w for w in words if len(w) > 1 and w not in STOP_WORDS]


class KnowledgeRetrievalService:
    """Lightweight relevance retrieval engine for organization knowledge records."""

    def retrieve_relevant_knowledge(
        self,
        db: Session,
        question: str,
        top_n: int = 3,
        category: Optional[str] = None,
        month: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> List[OrganizationKnowledge]:
        """Retrieve top-N most relevant knowledge records using lightweight scoring.

        Scoring combines:
        - Query keyword token overlap with title, tags, category, and content.
        - Exact tag and category matches.
        - Month matches (e.g. June 2026).
        """
        all_records = db.query(OrganizationKnowledge).all()
        if not all_records:
            logger.info("No knowledge records available in database for retrieval.")
            return []

        q_tokens = set(tokenize(question))
        q_raw_lower = question.lower().strip() if question else ""

        scored_records: List[Tuple[float, OrganizationKnowledge]] = []

        for record in all_records:
            score = 0.0

            # Filter level checks
            if category and record.category.lower() == category.lower():
                score += 15.0

            if month and record.month and record.month.lower() == month.lower():
                score += 15.0

            if tags:
                record_tags = [t.strip().lower() for t in (record.tags or "").split(",") if t.strip()]
                for target_tag in tags:
                    if target_tag.lower() in record_tags:
                        score += 20.0

            # 1. Tags matching in question
            if record.tags:
                record_tags = [t.strip().lower() for t in record.tags.split(",") if t.strip()]
                for tag_val in record_tags:
                    if tag_val in q_raw_lower:
                        score += 25.0
                    elif any(t_tok in q_tokens for t_tok in tokenize(tag_val)):
                        score += 12.0

            # 2. Title matching
            title_tokens = tokenize(record.title)
            title_matches = q_tokens.intersection(set(title_tokens))
            score += len(title_matches) * 15.0

            # 3. Category matching in question
            if record.category and record.category.lower() in q_raw_lower:
                score += 10.0

            # 4. Month matching in question
            if record.month and record.month.lower() in q_raw_lower:
                score += 15.0

            # 5. Content token overlap
            content_tokens = tokenize(record.content)
            content_matches = q_tokens.intersection(set(content_tokens))
            score += len(content_matches) * 3.0

            # 6. Multi-word phrase matching bonus
            for q_tok in q_tokens:
                if len(q_tok) > 3 and q_tok in record.content.lower():
                    score += 2.0

            scored_records.append((score, record))

        # Sort by score descending, then by creation date descending
        scored_records.sort(key=lambda x: (x[0], x[1].created_at or datetime.min), reverse=True)

        # Filter out records with score == 0 if we have non-zero scored records
        non_zero_results = [rec for sc, rec in scored_records if sc > 0]
        if non_zero_results:
            results = non_zero_results[:top_n]
        else:
            # Fallback: if no keyword matches found, return newest top_n entries
            results = [rec for sc, rec in scored_records[:top_n]]

        logger.info(
            "Retrieved top-%d relevant knowledge entries out of %d candidates for query='%s'",
            len(results), len(all_records), question
        )
        return results
