
# src/tools/portfolio_math.py
"""
Pure math functions for portfolio analysis and dollar-based deployment.

KEY DESIGN DECISIONS:
1. All recommendations in dollar amounts (matches Fidelity)
2. Supports category-level targets (ETF: 60%, Stocks: 30%, Gold: 10%)
3. Position caps strictly enforced — excess becomes cash
4. No network calls, no LLM, no side effects
"""

from src.models.portfolio import (
    Holding, PortfolioState, TickerScore,
    BuyRecommendation, DeploymentPlan,
)


def build_portfolio_state(
    holdings_config: list[dict],
    targets: dict[str, float],
    prices: dict[str, float],
) -> PortfolioState:
    """
    Combine config + live prices into a full portfolio snapshot.
    Computes allocation percentages and drift for every holding.
    """
    holdings = []
    total_value = 0.0
    total_cost = 0.0

    for h in holdings_config:
        t = h["ticker"]
        price = prices.get(t, 0.0)
        value = h["shares"] * price
        cost = h["shares"] * h["avg_cost_per_share"]
        total_value += value
        total_cost += cost
        holdings.append(Holding(
            ticker=t,
            shares=h["shares"],
            avg_cost=h["avg_cost_per_share"],
            current_price=price,
            current_value=round(value, 2),
            target_pct=targets.get(t, 0.0),
        ))

    for h in holdings:
        if total_value > 0:
            h.actual_pct = round(h.current_value / total_value * 100, 2)
        h.drift = round(h.actual_pct - h.target_pct, 2)

    return PortfolioState(
        holdings=holdings,
        total_value=round(total_value, 2),
        total_cost=round(total_cost, 2),
        total_return_pct=round(
            ((total_value - total_cost) / total_cost * 100) if total_cost > 0 else 0, 2
        ),
    )


def generate_deployment_plan(
    portfolio: PortfolioState,
    scores: dict[str, TickerScore],
    budget: float,
    max_single_pct: float = 0.40,
) -> DeploymentPlan:
    """
    Split monthly budget across holdings IN DOLLARS.

    STRATEGY: Weighted DCA with rebalance tilt.

    STEPS:
    1. Score each position by: 70% underweight need + 30% market score
    2. Skip overweight positions (drift > +2%)
    3. Convert weights to dollar amounts
    4. Hard cap each position at max_single_pct of budget
    5. Excess that cannot be redistributed becomes cash
    """
    max_single = budget * max_single_pct
    candidates = []

    for h in portfolio.holdings:
        score = scores.get(h.ticker)
        if not score or score.current_price <= 0:
            continue

        # Skip overweight positions
        if h.drift > 2:
            continue

        need = max(0, -h.drift)
        attractiveness = score.score / 10
        weight = (need * 0.7) + (attractiveness * 0.3)

        # Even on-target positions get small weight for steady DCA
        if weight == 0:
            weight = 0.1

        candidates.append({
            "ticker": h.ticker,
            "weight": weight,
            "score": score.score,
            "drift": h.drift,
            "price": score.current_price,
        })

    if not candidates:
        return DeploymentPlan(
            date=str(portfolio.timestamp.date()),
            budget=budget,
            strategy="weighted_dca",
            recommendations=[],
            cash_remaining=budget,
            summary="All positions overweight. Hold cash.",
        )

    # Normalize weights to dollar amounts
    total_weight = sum(c["weight"] for c in candidates)
    for c in candidates:
        c["dollars"] = (c["weight"] / total_weight) * budget

    # Apply cap — multiple passes to handle redistribution
    for _ in range(5):
        excess = 0.0
        uncapped_weight = 0.0

        # Find who is over the cap
        for c in candidates:
            if c["dollars"] > max_single:
                excess += c["dollars"] - max_single
                c["dollars"] = max_single
                c["capped"] = True
            else:
                c["capped"] = False
                uncapped_weight += c["weight"]

        # If no excess or nobody to absorb it, stop
        if excess <= 0 or uncapped_weight <= 0:
            break

        # Redistribute excess to uncapped positions
        for c in candidates:
            if not c["capped"]:
                c["dollars"] += (c["weight"] / uncapped_weight) * excess

    # Build final recommendations
    candidates.sort(key=lambda c: c["weight"], reverse=True)
    recommendations = []
    total_allocated = 0.0

    for c in candidates:
        # FINAL SAFETY: never exceed cap regardless of redistribution
        dollars = round(min(c["dollars"], max_single))

        if dollars < 10:
            continue

        if total_allocated + dollars > budget:
            dollars = round(budget - total_allocated)
            if dollars < 10:
                continue

        total_allocated += dollars

        recommendations.append(BuyRecommendation(
            ticker=c["ticker"],
            dollar_amount=dollars,
            pct_of_budget=round(dollars / budget * 100, 1),
            reasoning=f"Drift {c['drift']:+.1f}%, Score {c['score']}/10, ${c['price']:.2f}/share",
        ))

    return DeploymentPlan(
        date=str(portfolio.timestamp.date()),
        budget=budget,
        strategy="weighted_dca",
        recommendations=recommendations,
        cash_remaining=round(budget - total_allocated, 2),
    )