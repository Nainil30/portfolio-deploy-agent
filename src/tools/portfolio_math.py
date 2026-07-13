# src/tools/portfolio_math.py
"""
Pure math functions for portfolio analysis and dollar-based deployment.

TRANCHE SUPPORT:
  The monthly budget can be deployed as:
  - "lump_sum": Everything at once (simple)
  - "split_tranches": 60/25/15 split over the month

  When using tranches, this module generates plans for
  each tranche independently. The tranche budget is passed
  in — this module does not care which tranche it is.
  It just optimally deploys whatever budget it receives.
"""

from src.models.portfolio import (
    Holding, PortfolioState, TickerScore,
    BuyRecommendation, DeploymentPlan, DipAlert,
)


def build_portfolio_state(
    holdings_config: list[dict],
    targets: dict[str, float],
    prices: dict[str, float],
) -> PortfolioState:
    """Combine config + live prices into full portfolio snapshot."""
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


def detect_dips(
    scores: dict[str, TickerScore],
    dip_threshold: float = 2.0,
    deep_dip_threshold: float = 3.5,
) -> list[DipAlert]:
    """
    Scan all scored tickers for dip opportunities.

    A "dip" = price is X% below the 20-day SMA.
    A "deep dip" = price is Y% below the 20-day SMA.

    WHY 20-DAY SMA:
    Short enough to reflect recent price action.
    Long enough to smooth out single-day noise.
    A stock trading 3% below its 20-day average is
    meaningfully cheaper than recent history.
    """
    dips = []
    for ticker, s in scores.items():
        if s.sma_20 <= 0 or s.current_price <= 0:
            continue

        drop_pct = ((s.current_price - s.sma_20) / s.sma_20) * 100

        # Only negative drops are dips
        if drop_pct >= -dip_threshold:
            continue

        dips.append(DipAlert(
            ticker=ticker,
            current_price=s.current_price,
            sma_20=s.sma_20,
            drop_from_sma_pct=round(drop_pct, 1),
            score=s.score,
            is_deep_dip=drop_pct <= -deep_dip_threshold,
        ))

    # Sort by biggest drop first
    dips.sort(key=lambda d: d.drop_from_sma_pct)
    return dips


def generate_deployment_plan(
    portfolio: PortfolioState,
    scores: dict[str, TickerScore],
    budget: float,
    max_single_pct: float = 0.40,
    tranche: str = "full",
    target_tickers: list[str] | None = None,
) -> DeploymentPlan:
    """
    Split a budget across holdings in dollar amounts.

    PARAMS:
      portfolio:      Current portfolio state with drift
      scores:         Market attractiveness scores
      budget:         Dollar amount to deploy THIS tranche
      max_single_pct: Cap per position (fraction of THIS tranche budget)
      tranche:        Label: "full", "immediate", "dip_reserve", "deep_dip_reserve"
      target_tickers: If set, only deploy into these tickers (for dip buying)

    STRATEGY: Weighted DCA with rebalance tilt.
    70% weight from allocation need + 30% from market attractiveness.
    """
    max_single = budget * max_single_pct
    candidates = []

    for h in portfolio.holdings:
        # If targeting specific tickers (dip buy), only consider those
        if target_tickers and h.ticker not in target_tickers:
            continue

        score = scores.get(h.ticker)
        if not score or score.current_price <= 0:
            continue

        # Skip overweight positions (unless specifically targeted for dip buy)
        if h.drift > 2 and not target_tickers:
            continue

        need = max(0, -h.drift)
        attractiveness = score.score / 10
        weight = (need * 0.7) + (attractiveness * 0.3)

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
            tranche=tranche,
            recommendations=[],
            cash_remaining=budget,
            summary="No buy candidates found.",
        )

    # Normalize weights to dollar amounts
    total_weight = sum(c["weight"] for c in candidates)
    for c in candidates:
        c["dollars"] = (c["weight"] / total_weight) * budget

    # Apply cap with redistribution
    for _ in range(5):
        excess = 0.0
        uncapped_weight = 0.0

        for c in candidates:
            if c["dollars"] > max_single:
                excess += c["dollars"] - max_single
                c["dollars"] = max_single
                c["capped"] = True
            else:
                c["capped"] = False
                uncapped_weight += c["weight"]

        if excess <= 0 or uncapped_weight <= 0:
            break

        for c in candidates:
            if not c["capped"]:
                c["dollars"] += (c["weight"] / uncapped_weight) * excess

    # Build recommendations
    candidates.sort(key=lambda c: c["weight"], reverse=True)
    recommendations = []
    total_allocated = 0.0

    for c in candidates:
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
            pct_of_budget=round(dollars / budget * 100, 1) if budget > 0 else 0,
            reasoning=f"Drift {c['drift']:+.1f}%, Score {c['score']}/10, ${c['price']:.2f}/share",
        ))

    return DeploymentPlan(
        date=str(portfolio.timestamp.date()),
        budget=budget,
        strategy="weighted_dca",
        tranche=tranche,
        recommendations=recommendations,
        cash_remaining=round(budget - total_allocated, 2),
    )