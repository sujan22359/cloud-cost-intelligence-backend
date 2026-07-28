"""Pydantic schemas for the Cost Optimization module."""

from __future__ import annotations

from pydantic import BaseModel, Field


class OptimizationRecommendation(BaseModel):
    """A single actionable cost optimization recommendation."""

    service: str = Field(description="AWS service name.")
    issue: str = Field(description="Short description of the identified cost issue.")
    reason: str = Field(description="Data-backed reason explaining why this is flagged.")
    business_impact: str = Field(description="Business impact description.")
    estimated_savings: str = Field(description="Estimated monthly savings (e.g., '$45/month').")
    recommended_action: str = Field(description="Concrete recommended action.")
    priority: str = Field(description="HIGH, MEDIUM, or LOW.")
    current_cost: float = Field(description="Current monthly cost in USD.")
    previous_cost: float | None = Field(default=None, description="Previous month cost in USD.")
    change_pct: float | None = Field(default=None, description="Month-over-month change percentage.")
    dimension: str | None = Field(default=None, description="The dimension analyzed (e.g. product, team, environment, region, account).")
    dimension_value: str | None = Field(default=None, description="The specific item name for this dimension recommendation.")


class OptimizationSummary(BaseModel):
    """High-level summary of optimization opportunities."""

    total_potential_savings: float
    high_priority_count: int
    medium_priority_count: int
    low_priority_count: int
    current_period: str | None
    previous_period: str | None
    total_current_spend: float


class OptimizationRecommendationResponse(BaseModel):
    """Full optimization recommendations response."""

    summary: OptimizationSummary
    recommendations: list[OptimizationRecommendation]
