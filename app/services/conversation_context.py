"""Conversation context for the AWS Cost Intelligence chatbot.

Stores the prior turn's intent, service, and period so that follow-up
questions can be resolved without the user repeating themselves.

Example follow-up patterns resolved:
  - "What about Lambda?"      (prior service: EC2)  → service=Lambda, same intent
  - "Show me its trend."      (prior service: RDS)  → service=RDS, intent=SERVICE_TREND
  - "Compare it with S3."     (prior: EC2)          → primary=EC2, target=S3
  - "What happened in May?"   (no prior month)      → period=May
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ConversationTurn:
    """Captured intent context from a single conversation turn.

    Passed to QuestionAnalysisService.analyze_question() as ``prior_turn``
    so the next question can reference the same service/period/intent.
    """
    intent: str | None = None
    service_name: str | None = None
    billing_period: str | None = None
    top_n: int | None = None

    def update_from_analysis(self, analysis: dict) -> None:
        """Overwrite fields with values from the latest analysis dict."""
        if analysis.get("analysis_type"):
            self.intent = analysis["analysis_type"]
        if analysis.get("service_name"):
            self.service_name = analysis["service_name"]
        if analysis.get("billing_period"):
            self.billing_period = analysis["billing_period"]
        if analysis.get("top_n"):
            self.top_n = analysis["top_n"]


@dataclass
class ConversationSession:
    """In-memory session that accumulates turns for a single chat session.

    The QuestionRouter holds one ConversationSession per instance.  Because
    FastAPI creates a new router per request via the DI dependency, the
    session is effectively per-request.  The frontend can extend this by
    passing ``conversation_history`` in future API versions — for now this
    keeps backward compatibility with the existing AskRequest schema.
    """
    turns: list[ConversationTurn] = field(default_factory=list)

    @property
    def last_turn(self) -> ConversationTurn | None:
        return self.turns[-1] if self.turns else None

    def push(self, turn: ConversationTurn) -> None:
        """Record a new turn (keep last 10 to bound memory)."""
        self.turns.append(turn)
        if len(self.turns) > 10:
            self.turns.pop(0)

    def build_turn_from_analysis(self, analysis: dict) -> ConversationTurn:
        """Create a ConversationTurn from a freshly produced analysis dict."""
        return ConversationTurn(
            intent=analysis.get("analysis_type"),
            service_name=analysis.get("service_name"),
            billing_period=analysis.get("billing_period"),
            top_n=analysis.get("top_n"),
        )
