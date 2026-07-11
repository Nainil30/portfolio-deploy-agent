# src/tools/portfolio_math.py
"""
Pure math functions. No network calls. No LLM. No side effects.
Input data in, numbers out. Easy to test, easy to trust.

WHY SEPARATE FROM MARKET DATA:
market_data.py fetches from the internet (can fail, is slow).
This file does instant math on data already fetched.
Different responsibilities, different failure modes.
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

    # Calculate percentages and drift
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
    Decide how to split the monthly budget across holdings.

    STRATEGY: Weighted DCA with rebalance tilt.
    - Underweight positions get more money
    - Higher market scores (cheaper/oversold) get a bonus
    - Overweight positions are skipped
    - No single buy exceeds max_single_pct of budget

    The weights are: 70% allocation need + 30% market attractiveness
    """
    max_single = budget * max_single_pct
    candidates = []

    for h in portfolio.holdings:
        score = scores.get(h.ticker)
        if not score or score.current_price <= 0:
            continue

        # Skip overweight positions (drift > +2%)
        if h.drift > 2:
            continue

        # How underweight is this position (negative drift → positive need)
        need = max(0, -h.drift)
        attractiveness = score.score / 10  # Normalize 0 to 1

        # Combined weight
        weight = (need * 0.7) + (attractiveness * 0.3)

        # Even on-target positions get a small weight for DCA
        if weight == 0:
            weight = 0.1

        candidates.append({
            "ticker": h.ticker,
            "weight": weight,
            "price": score.current_price,
            "score": score.score,
            "drift": h.drift,
        })

    # Handle edge case: nothing to buy
    if not candidates:
        return DeploymentPlan(
            date=str(portfolio.timestamp.date()),
            budget=budget,
            strategy="weighted_dca",
            recommendations=[],
            cash_remaining=budget,
            summary="All positions overweight. Hold cash.",
        )

    # Normalize weights and allocate budget
    total_weight = sum(c["weight"] for c in candidates)
    for c in candidates:
        raw_allocation = (c["weight"] / total_weight) * budget
        c["allocation"] = min(raw_allocation, max_single)

    # Convert to whole shares, highest priority first
    candidates.sort(key=lambda x: x["weight"], reverse=True)
    recommendations = []
    spent = 0.0

    for c in candidates:
        remaining = budget - spent
        allocation = min(c["allocation"], remaining)
        shares = int(allocation // c["price"])

        if shares <= 0:
            continue

        cost = round(shares * c["price"], 2)
        spent += cost

        recommendations.append(BuyRecommendation(
            ticker=c["ticker"],
            shares_to_buy=shares,
            estimated_cost=cost,
            reasoning=f"Drift {c['drift']:+.1f}%, Score {c['score']}/10",
        ))

    return DeploymentPlan(
        date=str(portfolio.timestamp.date()),
        budget=budget,
        strategy="weighted_dca",
        recommendations=recommendations,
        cash_remaining=round(budget - spent, 2),
    )