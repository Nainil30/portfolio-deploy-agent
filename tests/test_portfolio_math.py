# tests/test_portfolio_math.py
"""
Unit tests for portfolio math.
Run with: pytest tests/ -v
"""

from src.tools.portfolio_math import build_portfolio_state, generate_deployment_plan
from src.models.portfolio import TickerScore


def _make_score(ticker, price, score=5):
    """Helper to create a TickerScore without repeating boilerplate."""
    return TickerScore(
        ticker=ticker,
        current_price=price,
        sma_20=price,
        rsi=50,
        drawdown_from_high_pct=-5,
        consecutive_red_days=0,
        score=score,
    )


def test_portfolio_state_computes_drift():
    """Drift correctly identifies overweight and underweight positions."""
    holdings = [
        {"ticker": "VOO", "shares": 10, "avg_cost_per_share": 400},
        {"ticker": "GLD", "shares": 5, "avg_cost_per_share": 200},
    ]
    targets = {"VOO": 70, "GLD": 30}
    prices = {"VOO": 500.0, "GLD": 250.0}

    state = build_portfolio_state(holdings, targets, prices)

    assert state.holdings[0].drift == 10.0
    assert state.holdings[1].drift == -10.0


def test_deployment_uses_full_budget_multiple_candidates():
    """
    When multiple candidates exist, most of the budget gets deployed.

    SCENARIO: 4 tickers, all slightly underweight.
    With 4 candidates and 40% cap, each can get up to $600.
    4 × $375 = $1,500 fits perfectly.
    """
    holdings = [
        {"ticker": "A", "shares": 5, "avg_cost_per_share": 100},
        {"ticker": "B", "shares": 5, "avg_cost_per_share": 100},
        {"ticker": "C", "shares": 5, "avg_cost_per_share": 100},
        {"ticker": "D", "shares": 5, "avg_cost_per_share": 100},
    ]
    targets = {"A": 25, "B": 25, "C": 25, "D": 25}
    prices = {"A": 100.0, "B": 100.0, "C": 100.0, "D": 100.0}

    portfolio = build_portfolio_state(holdings, targets, prices)
    scores = {
        "A": _make_score("A", 100, score=7),
        "B": _make_score("B", 100, score=6),
        "C": _make_score("C", 100, score=5),
        "D": _make_score("D", 100, score=4),
    }

    plan = generate_deployment_plan(portfolio, scores, budget=1500.0)
    total = sum(r.dollar_amount for r in plan.recommendations)

    # With 4 candidates under cap, most of budget should deploy
    assert total >= 1400
    assert plan.cash_remaining <= 100


def test_single_candidate_respects_cap():
    """
    When only one candidate exists, cap limits deployment.
    Excess becomes cash, not forced allocation.

    WHY THIS IS CORRECT:
    If you can only buy one thing and your rule is "max 40%
    in any single position", you should hold the rest as cash
    rather than violate your own rule.
    """
    holdings = [
        {"ticker": "VOO", "shares": 10, "avg_cost_per_share": 400},
        {"ticker": "GLD", "shares": 5, "avg_cost_per_share": 200},
    ]
    targets = {"VOO": 50, "GLD": 50}
    prices = {"VOO": 500.0, "GLD": 250.0}

    portfolio = build_portfolio_state(holdings, targets, prices)
    scores = {
        "VOO": _make_score("VOO", 500, score=6),
        "GLD": _make_score("GLD", 250, score=5),
    }

    plan = generate_deployment_plan(portfolio, scores, budget=1500.0)

    # VOO is overweight (+30% drift), so only GLD is a candidate
    # GLD capped at 40% of $1,500 = $600
    # Remaining $900 becomes cash
    assert len(plan.recommendations) == 1
    assert plan.recommendations[0].ticker == "GLD"
    assert plan.recommendations[0].dollar_amount <= 600
    assert plan.cash_remaining >= 900


def test_deployment_skips_overweight():
    """Overweight positions should not receive money."""
    holdings = [
        {"ticker": "VOO", "shares": 100, "avg_cost_per_share": 100},
        {"ticker": "GLD", "shares": 1, "avg_cost_per_share": 100},
    ]
    targets = {"VOO": 50, "GLD": 50}
    prices = {"VOO": 100.0, "GLD": 100.0}

    portfolio = build_portfolio_state(holdings, targets, prices)
    scores = {
        "VOO": _make_score("VOO", 100),
        "GLD": _make_score("GLD", 100),
    }

    plan = generate_deployment_plan(portfolio, scores, budget=500.0)

    tickers_in_plan = [r.ticker for r in plan.recommendations]
    assert "VOO" not in tickers_in_plan
    assert "GLD" in tickers_in_plan


def test_max_single_position_cap():
    """No single ticker should exceed the max cap percentage."""
    holdings = [
        {"ticker": "A", "shares": 1, "avg_cost_per_share": 100},
        {"ticker": "B", "shares": 1, "avg_cost_per_share": 100},
    ]
    targets = {"A": 90, "B": 10}
    prices = {"A": 100.0, "B": 100.0}

    portfolio = build_portfolio_state(holdings, targets, prices)
    scores = {
        "A": _make_score("A", 100),
        "B": _make_score("B", 100),
    }

    budget = 1000.0
    max_pct = 0.40
    plan = generate_deployment_plan(portfolio, scores, budget, max_pct)

    for r in plan.recommendations:
        assert r.dollar_amount <= (budget * max_pct) + 1


def test_empty_portfolio():
    """Handle edge case of no holdings gracefully."""
    portfolio = build_portfolio_state([], {}, {})
    assert portfolio.total_value == 0
    assert portfolio.total_cost == 0
    assert portfolio.holdings == []


def test_higher_score_gets_more_money():
    """
    Between two equally underweight positions,
    the one with a higher market score gets more money.
    We use a high cap (90%) so the cap does not flatten the difference.
    """
    holdings = [
        {"ticker": "A", "shares": 5, "avg_cost_per_share": 100},
        {"ticker": "B", "shares": 5, "avg_cost_per_share": 100},
    ]
    targets = {"A": 50, "B": 50}
    prices = {"A": 100.0, "B": 100.0}

    portfolio = build_portfolio_state(holdings, targets, prices)
    scores = {
        "A": _make_score("A", 100, score=9),
        "B": _make_score("B", 100, score=2),
    }

    # High cap so it does not interfere with the score-based split
    plan = generate_deployment_plan(portfolio, scores, budget=1000.0, max_single_pct=0.90)

    a_rec = next(r for r in plan.recommendations if r.ticker == "A")
    b_rec = next(r for r in plan.recommendations if r.ticker == "B")

    assert a_rec.dollar_amount > b_rec.dollar_amount