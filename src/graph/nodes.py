# src/graph/nodes.py
"""
Agent node implementations for LangGraph.

TRANCHE-AWARE DESIGN:
The agent checks what day of the month it is and which tranches
have already been deployed. Based on this, it decides:
  - Payday? → Deploy Tranche 1 (immediate)
  - Dip detected? → Deploy Tranche 2 (dip reserve)
  - Deep dip? → Deploy Tranche 3 (deep dip reserve)
  - End of month? → Deploy whatever is remaining
  - Nothing special? → "No action today" (silent)
"""

import json
from datetime import datetime
from langchain_core.messages import HumanMessage

from src.graph.state import AgentState
from src.utils.config_loader import load_config
from src.utils.llm_provider import get_llm
from src.tools.market_data import get_current_prices, analyze_ticker, get_vix
from src.tools.portfolio_math import (
    build_portfolio_state, generate_deployment_plan, detect_dips,
)
from src.tools.database import (
    save_snapshot, save_deployment, get_deployed_tranches_this_month,
)


# ═══════════════════════════════════════════════════════════════
# NODE 1: CONFIG LOADER
# ═══════════════════════════════════════════════════════════════

def load_config_node(state: AgentState) -> dict:
    """Load YAML config into state."""
    print("📋 Loading portfolio config...")
    config = load_config()
    print(f"   Budget: ${config['budget']['monthly_amount']:,.0f}")
    print(f"   Strategy: {config.get('strategy', 'lump_sum')}")
    print(f"   Holdings: {len(config['holdings'])} tickers")
    return {"config": config}


# ═══════════════════════════════════════════════════════════════
# NODE 2: PORTFOLIO TRACKER AGENT
# ═══════════════════════════════════════════════════════════════

def portfolio_tracker_node(state: AgentState) -> dict:
    """Fetch live prices and compute full portfolio state."""
    print("\n📊 Tracking portfolio...")
    config = state["config"]
    tickers = [h["ticker"] for h in config["holdings"]]

    prices = get_current_prices(tickers)
    for t, p in prices.items():
        print(f"   {t}: ${p:,.2f}")

    portfolio = build_portfolio_state(
        config["holdings"], config["target_allocation"], prices,
    )

    print(f"\n   Portfolio value: ${portfolio.total_value:,.2f}")
    print(f"   Total return:   {portfolio.total_return_pct:+.1f}%")

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
    Score tickers, detect dips, determine which tranche to deploy.

    DECISION LOGIC:
      1. What day of the month is it?
      2. Which tranches have already been deployed?
      3. Are there any dips right now?
      4. Based on all of this → generate the right deployment plan
    """
    print("\n🔍 Analyzing market conditions...")
    config = state["config"]
    portfolio = state["portfolio"]
    full_budget = config["budget"]["monthly_amount"]
    max_single_pct = config["budget"]["max_single_position_pct"]
    strategy = config.get("strategy", "lump_sum")

    # Score every ticker
    ticker_scores = {}
    for h in portfolio.holdings:
        score = analyze_ticker(h.ticker)
        ticker_scores[h.ticker] = score
        bar = "#" * score.score + "." * (10 - score.score)
        print(f"   {h.ticker:<6} [{bar}] {score.score}/10  {score.reasoning}")

    vix_data = get_vix()
    market_mood = vix_data["mood"]
    print(f"\n   VIX: {vix_data['vix']} → Market mood: {market_mood}")

    # Determine what to deploy
    if strategy == "split_tranches":
        plan, tranche_label = _handle_tranches(
            config, portfolio, ticker_scores, full_budget, max_single_pct,
        )
    
    else:
        # Lump sum — deploy everything at once
        check_only = state.get("check_only", False)
        deployed = get_deployed_tranches_this_month()

        if "full" in deployed and not check_only:
            plan = generate_deployment_plan(
                portfolio, ticker_scores, 0, tranche="full",
            )
            plan.summary = "Already deployed this month. Run with --check to see analysis anyway, or --reset to clear."
            tranche_label = "full (already deployed)"
        else:
            plan = generate_deployment_plan(
                portfolio, ticker_scores, full_budget, max_single_pct, tranche="full",
            )
            tranche_label = "full"

    print(f"\n💰 Tranche: {tranche_label}")
    print(f"   Deploying: ${plan.budget:,.0f}")
    for r in plan.recommendations:
        print(f"   → ${r.dollar_amount:,.0f} into {r.ticker} | {r.reasoning}")
    if plan.cash_remaining > 0:
        print(f"   Cash remaining: ${plan.cash_remaining:,.0f}")

    # Detect dips for awareness (even if not deploying now)
    tranches_config = config.get("tranches", {})
    dip_threshold = tranches_config.get("dip_threshold_pct", 2.0)
    deep_threshold = tranches_config.get("deep_dip_threshold_pct", 3.5)
    dip_alerts = detect_dips(ticker_scores, dip_threshold, deep_threshold)
    plan.dip_alerts = dip_alerts

    if dip_alerts:
        print(f"\n   📉 Dip alerts:")
        for d in dip_alerts:
            label = "DEEP DIP" if d.is_deep_dip else "DIP"
            print(f"      {d.ticker}: {d.drop_from_sma_pct:+.1f}% from SMA ({label})")

    # LLM commentary
    llm_config = config["llm"]
    llm = get_llm(provider=llm_config["provider"], model=llm_config["model"])

    feedback_note = ""
    if state.get("reflection_feedback"):
        feedback_note = f"\nFeedback to address: {state['reflection_feedback']}"

    prompt = f"""You are a portfolio deployment assistant. Write a 3-4 sentence
summary of today's recommendation. Be specific and factual.{feedback_note}

Portfolio: ${portfolio.total_value:,.0f} ({portfolio.total_return_pct:+.1f}%)
Market mood: {market_mood} (VIX: {vix_data['vix']})
Strategy: {strategy}
Tranche: {tranche_label} (${plan.budget:,.0f})

Deployment:
{_format_plan_for_llm(plan)}

Dip alerts: {[f"{d.ticker} {d.drop_from_sma_pct:+.1f}%" for d in dip_alerts] if dip_alerts else "None"}

Drift summary:
{_format_drift_for_llm(portfolio)}

Write ONLY the summary paragraph."""

    print("\n🧠 Generating AI analysis...")
    response = llm.invoke([HumanMessage(content=prompt)])
    plan.summary = response.content
    print(f"   {response.content}")

    return {
        "ticker_scores": ticker_scores,
        "market_mood": market_mood,
        "deployment_plan": plan,
        "analyst_commentary": response.content,
    }


def _handle_tranches(config, portfolio, scores, full_budget, max_single_pct):
    """
    Determine which tranche to deploy based on day of month
    and what has already been deployed.

    RETURNS: (plan, tranche_label)
    """
    today = datetime.now().day
    deployed = get_deployed_tranches_this_month()
    tranches_config = config.get("tranches", {})

    payday = config.get("schedule", {}).get("payday", 15)
    immediate_pct = tranches_config.get("immediate_pct", 60) / 100
    dip_pct = tranches_config.get("dip_reserve_pct", 25) / 100
    deep_pct = tranches_config.get("deep_dip_reserve_pct", 15) / 100
    dip_threshold = tranches_config.get("dip_threshold_pct", 2.0)
    deep_threshold = tranches_config.get("deep_dip_threshold_pct", 3.5)
    dip_deadline = tranches_config.get("dip_deadline_day", 20)
    final_deadline = tranches_config.get("final_deadline_day", 28)

    dips = detect_dips(scores, dip_threshold, deep_threshold)
    dip_tickers = [d.ticker for d in dips if not d.is_deep_dip]
    deep_dip_tickers = [d.ticker for d in dips if d.is_deep_dip]

    # Decision tree
    if "immediate" not in deployed and today >= payday:
        # Tranche 1: Payday deployment
        budget = round(full_budget * immediate_pct)
        plan = generate_deployment_plan(
            portfolio, scores, budget, max_single_pct, tranche="immediate",
        )
        return plan, f"immediate ({immediate_pct:.0%} = ${budget:,.0f})"

    elif "dip_reserve" not in deployed:
        if deep_dip_tickers:
            # Deep dip found — deploy dip reserve into dip tickers
            budget = round(full_budget * dip_pct)
            plan = generate_deployment_plan(
                portfolio, scores, budget, max_single_pct,
                tranche="dip_reserve", target_tickers=deep_dip_tickers,
            )
            return plan, f"dip_reserve — DEEP DIP on {deep_dip_tickers}"

        elif dip_tickers:
            # Regular dip found
            budget = round(full_budget * dip_pct)
            plan = generate_deployment_plan(
                portfolio, scores, budget, max_single_pct,
                tranche="dip_reserve", target_tickers=dip_tickers,
            )
            return plan, f"dip_reserve — DIP on {dip_tickers}"

        elif today >= dip_deadline:
            # No dip by deadline — deploy anyway
            budget = round(full_budget * dip_pct)
            plan = generate_deployment_plan(
                portfolio, scores, budget, max_single_pct,
                tranche="dip_reserve",
            )
            return plan, f"dip_reserve — no dip by day {dip_deadline}, deploying anyway"

        else:
            # No dip yet, still waiting
            plan = generate_deployment_plan(
                portfolio, scores, 0, tranche="dip_reserve",
            )
            plan.summary = f"Watching for dips. Reserve: ${full_budget * dip_pct:,.0f}"
            return plan, "dip_reserve — WAITING for dip"

    elif "deep_dip_reserve" not in deployed:
        if deep_dip_tickers:
            budget = round(full_budget * deep_pct)
            plan = generate_deployment_plan(
                portfolio, scores, budget, max_single_pct,
                tranche="deep_dip_reserve", target_tickers=deep_dip_tickers,
            )
            return plan, f"deep_dip_reserve — DEEP DIP on {deep_dip_tickers}"

        elif today >= final_deadline:
            # Month ending — deploy everything remaining
            budget = round(full_budget * deep_pct)
            plan = generate_deployment_plan(
                portfolio, scores, budget, max_single_pct,
                tranche="deep_dip_reserve",
            )
            return plan, f"deep_dip_reserve — month ending, deploying remaining"

        else:
            plan = generate_deployment_plan(
                portfolio, scores, 0, tranche="deep_dip_reserve",
            )
            plan.summary = f"Watching for deep dips. Reserve: ${full_budget * deep_pct:,.0f}"
            return plan, "deep_dip_reserve — WAITING for deep dip"

    else:
        # All tranches deployed this month
        check_only = True  # Handled by parent function
        plan = generate_deployment_plan(
            portfolio, scores, 0, tranche="all_deployed",
        )
        plan.summary = "All tranches deployed this month. Run with --check to see fresh analysis, or --reset to clear."
        return plan, "ALL DEPLOYED this month"

def _format_drift_for_llm(portfolio) -> str:
    lines = []
    for h in sorted(portfolio.holdings, key=lambda x: x.drift):
        status = "UNDERWEIGHT" if h.drift < -2 else "OVERWEIGHT" if h.drift > 2 else "on-target"
        lines.append(f"  {h.ticker}: target {h.target_pct}%, actual {h.actual_pct}%, drift {h.drift:+.1f}% ({status})")
    return "\n".join(lines)


def _format_plan_for_llm(plan) -> str:
    if not plan.recommendations:
        return "  No deployment this run."
    lines = []
    for r in plan.recommendations:
        lines.append(f"  ${r.dollar_amount:,.0f} → {r.ticker} ({r.reasoning})")
    lines.append(f"  Cash remaining: ${plan.cash_remaining:,.0f}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# NODE 4: REFLECTION AGENT
# ═══════════════════════════════════════════════════════════════

def reflection_node(state: AgentState) -> dict:
    """Self-critique: review the deployment plan for issues."""
    print("\n🔄 Reflection agent reviewing plan...")
    plan = state["deployment_plan"]
    portfolio = state["portfolio"]
    config = state["config"]

    # If no deployment this run (waiting for dip), auto-approve
    if plan.budget == 0:
        print("   ✅ No deployment this run — auto-approved")
        return {"plan_approved": True, "reflection_feedback": "", "revision_count": state["revision_count"]}

    budget = plan.budget
    max_single_pct = config["budget"]["max_single_position_pct"]
    max_single = budget * max_single_pct
    issues = []

    total_spend = sum(r.dollar_amount for r in plan.recommendations)
    if total_spend > budget + 1:
        issues.append(f"Total ${total_spend:,.0f} exceeds budget ${budget:,.0f}")

    for r in plan.recommendations:
        if r.dollar_amount > max_single + 1:
            issues.append(f"{r.ticker}: ${r.dollar_amount:,.0f} exceeds cap ${max_single:,.0f}")

    sorted_holdings = sorted(portfolio.holdings, key=lambda h: h.drift)
    most_underweight = sorted_holdings[0]
    planned_tickers = {r.ticker for r in plan.recommendations}

    if most_underweight.drift < -3 and most_underweight.ticker not in planned_tickers:
        issues.append(f"Most underweight {most_underweight.ticker} ({most_underweight.drift:+.1f}%) missing from plan")

    if not plan.recommendations and budget > 0:
        has_underweight = any(h.drift < -1 for h in portfolio.holdings)
        if has_underweight:
            issues.append("Empty plan despite underweight positions")

    if issues:
        print(f"   ❌ Issues: {'; '.join(issues)}")
        return {
            "plan_approved": False,
            "reflection_feedback": "; ".join(issues),
            "revision_count": state["revision_count"] + 1,
        }

    print("   ✅ Plan approved")
    return {"plan_approved": True, "reflection_feedback": "", "revision_count": state["revision_count"]}


# ═══════════════════════════════════════════════════════════════
# NODE 5: NOTIFICATION AGENT
# ═══════════════════════════════════════════════════════════════

def notification_node(state: AgentState) -> dict:
    """Format and deliver the recommendation."""
    plan = state["deployment_plan"]
    portfolio = state["portfolio"]
    mood = state["market_mood"]

    # Save to database
    plan_dict = {
        "date": plan.date,
        "budget": plan.budget,
        "strategy": plan.strategy,
        "tranche": plan.tranche,
        "cash_remaining": plan.cash_remaining,
        "summary": plan.summary,
        "recommendations": [r.model_dump() for r in plan.recommendations],
        "dip_alerts": [d.model_dump() for d in plan.dip_alerts],
    }

    # Only save if there is something to deploy or report
    if plan.budget > 0 or plan.dip_alerts:
        save_deployment(budget=plan.budget, plan=plan_dict, tranche=plan.tranche)

    msg = _build_notification(plan, portfolio, mood)
    print("\n" + msg)

    # Send via Telegram
    from src.notifications.telegram_bot import notify
    sent = notify(msg)
    if sent:
        print("\n   ✅ Telegram notification sent!")

    return {"notification_sent": True}


def _build_notification(plan, portfolio, mood: str) -> str:
    """Build the deployment notification message."""
    lines = [
        "=" * 50,
        "PORTFOLIO DEPLOYMENT AGENT",
        "=" * 50,
        f"Date: {plan.date}",
        f"Tranche: {plan.tranche}",
        f"Market: {mood}",
        f"Portfolio: ${portfolio.total_value:,.2f} ({portfolio.total_return_pct:+.1f}%)",
        "",
    ]

    if plan.recommendations:
        lines.append(f"DEPLOY ${plan.budget:,.0f} IN FIDELITY:")
        lines.append("-" * 50)
        for r in plan.recommendations:
            lines.append(f"  Buy ${r.dollar_amount:>7,.0f} of {r.ticker:<6} | {r.reasoning}")
        total = sum(r.dollar_amount for r in plan.recommendations)
        lines.append("-" * 50)
        lines.append(f"  Total: ${total:,.0f}")
        if plan.cash_remaining > 0:
            lines.append(f"  Cash remaining: ${plan.cash_remaining:,.0f}")
    else:
        lines.append("  No deployment this run.")

    if plan.dip_alerts:
        lines.append("")
        lines.append("DIP ALERTS:")
        for d in plan.dip_alerts:
            label = "DEEP" if d.is_deep_dip else "    "
            lines.append(f"  {label} {d.ticker}: {d.drop_from_sma_pct:+.1f}% from SMA")

    lines.extend([
        "",
        plan.summary,
        "",
        "Personal tool, not financial advice.",
        "=" * 50,
    ])

    return "\n".join(lines)

# ═══════════════════════════════════════════════════════════════
# NODE 6: CHECK-ONLY OUTPUT (no save, no notify)
# ═══════════════════════════════════════════════════════════════

def check_only_node(state: AgentState) -> dict:
    """
    Display the recommendation without saving or sending.
    Safe to run every day without side effects.
    """
    plan = state["deployment_plan"]
    portfolio = state["portfolio"]
    mood = state["market_mood"]

    msg = _build_notification(plan, portfolio, mood)
    print("\n" + msg)
    print("\n   ℹ️  CHECK MODE — Nothing saved. Nothing sent to Telegram.")

    return {"notification_sent": False}