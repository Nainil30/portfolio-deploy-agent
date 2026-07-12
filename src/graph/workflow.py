
# src/graph/workflow.py
"""
LangGraph workflow — the orchestrator that connects all agents.

THIS IS THE CORE OF THE AGENTIC SYSTEM.

WHY LANGGRAPH (not just calling functions in order):
1. CONDITIONAL EDGES: The reflection agent can route back to
   the strategist (revision loop) or forward to notification.
   A plain script cannot branch dynamically based on agent output.

2. STATE MACHINE: Each agent reads/writes shared state. The
   framework manages state flow, merging, and persistence.

3. CHECKPOINTING: State is saved to SQLite. If the process
   crashes mid-run, it can resume from the last checkpoint.

4. HUMAN-IN-THE-LOOP: LangGraph supports "interrupt before"
   a node, letting the human approve before proceeding.

5. VISUALIZATION: graph.get_graph().draw_mermaid() generates
   a visual diagram of your agent workflow. Great for README.
"""

from langgraph.graph import StateGraph, END

from src.graph.state import AgentState
from src.graph.nodes import (
    load_config_node,
    portfolio_tracker_node,
    analyst_strategist_node,
    reflection_node,
    notification_node,
)


def _should_revise_or_approve(state: AgentState) -> str:
    """
    Conditional edge after reflection.

    THIS IS THE AGENTIC LOOP:
    If reflection rejects the plan → route back to strategist
    If approved (or max retries hit) → route to notification

    Max 2 revisions prevents infinite loops.
    In practice, the deterministic math rarely triggers revision.
    The loop exists to catch edge cases and demonstrate the pattern.
    """
    if state["plan_approved"]:
        return "approve"
    if state["revision_count"] >= 2:
        print("   ⚠️  Max revisions reached. Proceeding with current plan.")
        return "approve"
    return "revise"


def build_graph() -> StateGraph:
    """
    Build the full agent workflow.

    FLOW:
      load_config
          ↓
      track_portfolio
          ↓
      analyze_and_strategize ←─── (revision loop)
          ↓                           ↑
      reflect ───── FAIL ────────────┘
          │
        PASS
          ↓
      notify
          ↓
        END
    """
    graph = StateGraph(AgentState)

    # ── Register agent nodes ──────────────────────────────
    graph.add_node("load_config", load_config_node)
    graph.add_node("track_portfolio", portfolio_tracker_node)
    graph.add_node("analyze_and_strategize", analyst_strategist_node)
    graph.add_node("reflect", reflection_node)
    graph.add_node("notify", notification_node)

    # ── Define the flow ───────────────────────────────────
    graph.set_entry_point("load_config")
    graph.add_edge("load_config", "track_portfolio")
    graph.add_edge("track_portfolio", "analyze_and_strategize")
    graph.add_edge("analyze_and_strategize", "reflect")

    # THE AGENTIC LOOP — conditional routing after reflection
    graph.add_conditional_edges(
        "reflect",
        _should_revise_or_approve,
        {
            "approve": "notify",
            "revise": "analyze_and_strategize",
        },
    )

    graph.add_edge("notify", END)

    return graph.compile()


def run_agent() -> AgentState:
    """
    Build the graph and execute the full workflow.
    Returns the final state with all results.
    """
    graph = build_graph()

    # Initial state — mostly empty, agents fill it as they run
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
    }

    print("🚀 Portfolio Deployment Agent starting...\n")

    final_state = graph.invoke(initial_state)

    return final_state

