
# src/graph/state.py
"""LangGraph shared state."""

from typing import TypedDict, Any
from src.models.portfolio import PortfolioState, DeploymentPlan, TickerScore


class AgentState(TypedDict):
    config: dict[str, Any]
    portfolio: PortfolioState | None
    ticker_scores: dict[str, TickerScore]
    market_mood: str
    deployment_plan: DeploymentPlan | None
    analyst_commentary: str
    reflection_feedback: str
    plan_approved: bool
    revision_count: int
    notification_sent: bool
    error: str | None
    check_only: bool