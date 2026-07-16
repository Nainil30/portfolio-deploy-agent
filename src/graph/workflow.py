

# src/graph/workflow.py
"""
LangGraph workflow — the orchestrator.
Supports check_only mode: analyze without saving or notifying.
"""

from langgraph.graph import StateGraph, END

from src.graph.state import AgentState
from src.graph.nodes import (
    load_config_node,
    portfolio_tracker_node,
    analyst_strategist_node,
    reflection_node,
    notification_node,
    check_only_node,
)


def _should_revise_or_approve(state: AgentState) -> str:
    if state["plan_approved"]:
        return "approve"
    if state["revision_count"] >= 2:
        return "approve"
    return "revise"


def _check_or_notify(state: AgentState) -> str:
    """Route to check-only output or full notification."""
    if state.get("check_only", False):
        return "check_output"
    return "notify"


def build_graph(check_only: bool = False) -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("load_config", load_config_node)
    graph.add_node("track_portfolio", portfolio_tracker_node)
    graph.add_node("analyze_and_strategize", analyst_strategist_node)
    graph.add_node("reflect", reflection_node)
    graph.add_node("notify", notification_node)
    graph.add_node("check_output", check_only_node)

    graph.set_entry_point("load_config")
    graph.add_edge("load_config", "track_portfolio")
    graph.add_edge("track_portfolio", "analyze_and_strategize")
    graph.add_edge("analyze_and_strategize", "reflect")

    graph.add_conditional_edges(
        "reflect",
        _should_revise_or_approve,
        {
            "approve": "route_output",
            "revise": "analyze_and_strategize",
        },
    )

    # Route to check-only or full notification
    graph.add_node("route_output", lambda state: state)
    graph.add_conditional_edges(
        "route_output",
        _check_or_notify,
        {
            "check_output": "check_output",
            "notify": "notify",
        },
    )

    graph.add_edge("notify", END)
    graph.add_edge("check_output", END)

    return graph.compile()


def run_agent(check_only: bool = False) -> AgentState:
    graph = build_graph(check_only=check_only)

    initial_state: AgentState = {
        "config": {},
        "portfolio": None,
        "ticker_scores": {},
        "market_mood": "",
        "deployment_plan": None,
        "analyst_commentary": "",
        "reflection_feedback": "",
        "plan_approved": False,
        "revision_count": 0,
        "notification_sent": False,
        "error": None,
        "check_only": check_only,
    }

    final_state = graph.invoke(initial_state)
    return final_state


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