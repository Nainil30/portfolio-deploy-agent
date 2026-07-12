# src/graph/state.py
"""
LangGraph shared state — the "memory" that flows between agents.

WHY TypedDict:
LangGraph passes this object through every node. Each agent reads
what it needs and writes its outputs. TypedDict gives us type
safety and documentation of what each field means.

ANALOGY:
Think of this as a clipboard being passed around an office.
Each person (agent) reads the relevant sections, writes their
part, and passes it to the next person.
"""

from typing import TypedDict, Any

from src.models.portfolio import PortfolioState, DeploymentPlan, TickerScore


class AgentState(TypedDict):
    """Shared state flowing through the LangGraph workflow."""

    # ── Set by config loader ──────────────────────────────
    config: dict[str, Any]

    # ── Set by portfolio tracker agent ────────────────────
    portfolio: PortfolioState | None

    # ── Set by analyst/strategist agent ───────────────────
    ticker_scores: dict[str, TickerScore]
    market_mood: str
    deployment_plan: DeploymentPlan | None
    analyst_commentary: str

    # ── Set by reflection agent ───────────────────────────
    # These control the agentic loop
    reflection_feedback: str   # What was wrong with the plan
    plan_approved: bool        # Should we proceed or revise
    revision_count: int        # How many times we have looped

    # ── Set by notification agent ─────────────────────────
    notification_sent: bool
    error: str | None