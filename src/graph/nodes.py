
# src/graph/nodes.py
"""
Agent node implementations for LangGraph.

PATTERN: Each function takes the full AgentState, does its job,
and returns ONLY the fields it changed. LangGraph merges the
returned dict into the existing state automatically.

WHY THIS IS "AGENTIC" AND NOT JUST FUNCTIONS:
1. Agents communicate through shared state (not direct calls)
2. The LLM reasons about data and generates analysis
3. The reflection agent can REJECT and LOOP BACK
4. The workflow has conditional branching (not linear)
5. State persists across runs via checkpointing
"""

import json
from langchain_core.messages import HumanMessage

from src.graph.state import AgentState
from src.utils.config_loader import load_config
from src.utils.llm_provider import get_llm
from src.tools.market_data import get_current_prices, analyze_ticker, get_vix
from src.tools.portfolio_math import build_portfolio_state, generate_deployment_plan
from src.tools.database import save_snapshot, save_deployment


# ═══════════════════════════════════════════════════════════════
# NODE 1: CONFIG LOADER
# ═══════════════════════════════════════════════════════════════

def load_config_node(state: AgentState) -> dict:
    """
    First node. Loads YAML config into state.
    Every other agent reads from state["config"].

    WHY A SEPARATE NODE:
    If config loading fails (bad YAML, missing file), we want
    the error to happen HERE with a clear message, not buried
    inside another agent.
    """
    print("📋 Loading portfolio config...")
    config = load_config()
    print(f"   Budget: ${config['budget']['monthly_amount']:,.0f}")
    print(f"   Holdings: {len(config['holdings'])} tickers")
    return {"config": config}


# ═══════════════════════════════════════════════════════════════
# NODE 2: PORTFOLIO TRACKER AGENT
# ═══════════════════════════════════════════════════════════════

def portfolio_tracker_node(state: AgentState) -> dict:
    """
    Fetches live prices and computes full portfolio state.

    WHAT MAKES THIS AN "AGENT":
    It actively reaches out to an external system (Yahoo Finance),
    retrieves real-time data, and transforms it into structured
    portfolio analysis. It also persists the snapshot to database
    for historical tracking.
    """
    print("\n📊 Tracking portfolio...")
    config = state["config"]
    tickers = [h["ticker"] for h in config["holdings"]]

    # Fetch live prices
    prices = get_current_prices(tickers)
    for t, p in prices.items():
        print(f"   {t}: ${p:,.2f}")

    # Build portfolio snapshot
    portfolio = build_portfolio_state(
        config["holdings"],
        config["target_allocation"],
        prices,
    )

    print(f"\n   Portfolio value: ${portfolio.total_value:,.2f}")
    print(f"   Total return:   {portfolio.total_return_pct:+.1f}%")

    # Save snapshot for historical tracking
    save_snapshot(
        total_value=portfolio.total_value,
        total_cost=portfolio.total_cost,
        holdings=[h.model_dump() for h in portfolio.holdings],
    )

    return {"portfolio": portfolio}


# ═══════════════════════════════════════════════════════════════
# NODE 3: ANALYST + STRATEGIST AGENT
# ═══════════════════════════════════════════════════════════════

def analyst_strategist_node(state: AgentState) -> dict:
    """
    Two-phase agent:
      Phase A (Python): Score tickers + generate dollar deployment plan
      Phase B (LLM):    Generate human-readable analysis summary

    WHY COMBINED:
    Splitting analysis and strategy into separate agents added
    complexity without value. One node handles the full pipeline.

    WHY THE LLM IS HERE:
    The math is done by Python (deterministic, trustworthy).
    The LLM adds COMMUNICATION — a natural language summary
    that explains the reasoning. This is what shows up in your
    Telegram notification and makes the output human-friendly.
    """
    print("\n🔍 Analyzing market conditions...")
    config = state["config"]
    portfolio = state["portfolio"]
    budget = config["budget"]["monthly_amount"]
    max_single_pct = config["budget"]["max_single_position_pct"]

    # ── Phase A: Deterministic scoring and math ──────────
    ticker_scores = {}
    for h in portfolio.holdings:
        score = analyze_ticker(h.ticker)
        ticker_scores[h.ticker] = score
        bar = "#" * score.score + "." * (10 - score.score)
        print(f"   {h.ticker:<6} [{bar}] {score.score}/10  {score.reasoning}")

    # Market mood via VIX
    vix_data = get_vix()
    market_mood = vix_data["mood"]
    print(f"\n   VIX: {vix_data['vix']} → Market mood: {market_mood}")

    # Generate dollar-based deployment plan
    plan = generate_deployment_plan(
        portfolio=portfolio,
        scores=ticker_scores,
        budget=budget,
        max_single_pct=max_single_pct,
    )

    print(f"\n💰 Deployment plan (${budget:,.0f}):")
    for r in plan.recommendations:
        print(f"   → ${r.dollar_amount:,.0f} into {r.ticker} | {r.reasoning}")
    print(f"   Cash remaining: ${plan.cash_remaining:,.0f}")

    # ── Phase B: LLM generates human-readable summary ────
    # If reflection agent sent feedback, include it so the
    # LLM can address concerns in the revised summary
    feedback_note = ""
    if state.get("reflection_feedback"):
        feedback_note = (
            f"\n\nPREVIOUS FEEDBACK TO ADDRESS:\n{state['reflection_feedback']}"
        )

    llm_config = config["llm"]
    llm = get_llm(provider=llm_config["provider"], model=llm_config["model"])

    prompt = f"""You are a portfolio analysis assistant. Write a 3-4 sentence
summary explaining this month's deployment recommendation.

Be specific: mention which positions are underweight, which are skipped
and why, and whether market conditions favor buying now.
Be factual and concise. No hype. No disclaimers.{feedback_note}

PORTFOLIO:
Total value: ${portfolio.total_value:,.2f}
Total return: {portfolio.total_return_pct:+.1f}%
Market mood: {market_mood} (VIX: {vix_data['vix']})

DRIFT ANALYSIS:
{_format_drift_for_llm(portfolio)}

DEPLOYMENT PLAN (${budget:,.0f} budget):
{_format_plan_for_llm(plan)}

Write ONLY the summary paragraph. No headers or bullet points."""

    print("\n🧠 Generating AI analysis...")
    response = llm.invoke([HumanMessage(content=prompt)])
    commentary = response.content
    plan.summary = commentary
    print(f"   {commentary}")

    return {
        "ticker_scores": ticker_scores,
        "market_mood": market_mood,
        "deployment_plan": plan,
        "analyst_commentary": commentary,
    }


def _format_drift_for_llm(portfolio) -> str:
    """Format drift data as a string for the LLM prompt."""
    lines = []
    for h in sorted(portfolio.holdings, key=lambda x: x.drift):
        status = "UNDERWEIGHT" if h.drift < -2 else "OVERWEIGHT" if h.drift > 2 else "on-target"
        lines.append(f"  {h.ticker}: target {h.target_pct}%, actual {h.actual_pct}%, drift {h.drift:+.1f}% ({status})")
    return "\n".join(lines)


def _format_plan_for_llm(plan) -> str:
    """Format the deployment plan as a string for the LLM prompt."""
    if not plan.recommendations:
        return "  No buys recommended."
    lines = []
    for r in plan.recommendations:
        lines.append(f"  ${r.dollar_amount:,.0f} → {r.ticker} ({r.reasoning})")
    lines.append(f"  Cash remaining: ${plan.cash_remaining:,.0f}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# NODE 4: REFLECTION AGENT
# ═══════════════════════════════════════════════════════════════

def reflection_node(state: AgentState) -> dict:
    """
    Self-critique agent. Reviews the deployment plan for problems.

    WHY THIS MATTERS FOR YOUR PORTFOLIO:
    This is a second pair of eyes. Catches mistakes before you
    act on them.

    WHY THIS MATTERS FOR RECRUITERS:
    Reflection loops are a KEY agentic AI pattern. Shows you
    understand self-correcting systems, not just one-shot generation.
    Papers like "Reflexion" (2023) established this as a best practice.

    CHECKS:
    1. Total spend within budget
    2. No single position exceeds cap
    3. Most underweight position is addressed
    4. Plan is not empty when budget exists
    5. Overweight positions are not receiving money
    """
    print("\n🔄 Reflection agent reviewing plan...")
    plan = state["deployment_plan"]
    portfolio = state["portfolio"]
    config = state["config"]
    budget = config["budget"]["monthly_amount"]
    max_single_pct = config["budget"]["max_single_position_pct"]
    max_single = budget * max_single_pct

    issues = []

    # Check 1: Total spend within budget
    total_spend = sum(r.dollar_amount for r in plan.recommendations)
    if total_spend > budget + 1:  # +1 for rounding tolerance
        issues.append(f"Total ${total_spend:,.0f} exceeds budget ${budget:,.0f}")

    # Check 2: Single position cap
    for r in plan.recommendations:
        if r.dollar_amount > max_single + 1:
            issues.append(
                f"{r.ticker}: ${r.dollar_amount:,.0f} exceeds "
                f"cap ${max_single:,.0f}"
            )

    # Check 3: Most underweight position should be in plan
    sorted_by_drift = sorted(portfolio.holdings, key=lambda h: h.drift)
    most_underweight = sorted_by_drift[0]
    planned_tickers = {r.ticker for r in plan.recommendations}

    if most_underweight.drift < -3 and most_underweight.ticker not in planned_tickers:
        issues.append(
            f"Most underweight: {most_underweight.ticker} "
            f"(drift {most_underweight.drift:+.1f}%) not in plan"
        )

    # Check 4: Plan should not be empty
    if not plan.recommendations and budget > 0:
        # This is only an issue if there ARE underweight positions
        has_underweight = any(h.drift < -1 for h in portfolio.holdings)
        if has_underweight:
            issues.append("Empty plan despite underweight positions existing")

    # Check 5: No money going to overweight positions
    for r in plan.recommendations:
        holding = next((h for h in portfolio.holdings if h.ticker == r.ticker), None)
        if holding and holding.drift > 5:
            issues.append(
                f"{r.ticker} is overweight (drift {holding.drift:+.1f}%) "
                f"but receiving ${r.dollar_amount:,.0f}"
            )

    if issues:
        print(f"   ❌ Issues found: {'; '.join(issues)}")
        return {
            "plan_approved": False,
            "reflection_feedback": "; ".join(issues),
            "revision_count": state["revision_count"] + 1,
        }

    print("   ✅ Plan approved — no issues found")
    return {
        "plan_approved": True,
        "reflection_feedback": "",
        "revision_count": state["revision_count"],
    }


# ═══════════════════════════════════════════════════════════════
# NODE 5: NOTIFICATION AGENT
# ═══════════════════════════════════════════════════════════════

def notification_node(state: AgentState) -> dict:
    """
    Formats the final recommendation and delivers it.
    MVP: prints to console.
    Phase 5: sends via Telegram.
    """
    print("\n" + "=" * 60)
    plan = state["deployment_plan"]
    portfolio = state["portfolio"]
    mood = state["market_mood"]

    # Save to database for history tracking
    plan_dict = {
        "date": plan.date,
        "budget": plan.budget,
        "strategy": plan.strategy,
        "cash_remaining": plan.cash_remaining,
        "summary": plan.summary,
        "recommendations": [r.model_dump() for r in plan.recommendations],
    }
    save_deployment(budget=plan.budget, plan=plan_dict)

    # Format the message
    msg = _build_notification(plan, portfolio, mood)
    print(msg)

    # Phase 5: Uncomment to send via Telegram
    # from src.notifications.telegram_bot import notify
    # notify(msg)

    return {"notification_sent": True}


def _build_notification(plan, portfolio, mood: str) -> str:
    """Build the deployment notification message."""
    lines = [
        "=" * 60,
        "📊 PORTFOLIO DEPLOYMENT RECOMMENDATION",
        "=" * 60,
        f"📅 Date: {plan.date}",
        f"💰 Budget: ${plan.budget:,.2f}",
        f"🌡️  Market: {mood}",
        f"📈 Portfolio: ${portfolio.total_value:,.2f} ({portfolio.total_return_pct:+.1f}%)",
        "",
    ]

    if plan.recommendations:
        lines.append("🛒 EXECUTE IN FIDELITY:")
        lines.append("─" * 60)
        for r in plan.recommendations:
            lines.append(
                f"  → Buy ${r.dollar_amount:>8,.0f} of {r.ticker:<6} "
                f"({r.pct_of_budget:.0f}% of budget) | {r.reasoning}"
            )
        lines.append("─" * 60)
        total = sum(r.dollar_amount for r in plan.recommendations)
        lines.append(f"  Total: ${total:,.0f}  |  Cash remaining: ${plan.cash_remaining:,.0f}")
    else:
        lines.append("  No buys recommended this cycle.")

    lines.extend([
        "",
        f"🧠 {plan.summary}",
        "",
        "⚠️  Personal tool, not financial advice.",
        "=" * 60,
    ])

    return "\n".join(lines)
