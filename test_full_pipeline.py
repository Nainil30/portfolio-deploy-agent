# test_full_pipeline.py
"""
Full pipeline test: config → prices → portfolio → dollar-based deployment.
Run with: python test_full_pipeline.py
"""

from src.utils.config_loader import load_config
from src.tools.market_data import get_current_prices, analyze_ticker, get_vix
from src.tools.portfolio_math import build_portfolio_state, generate_deployment_plan
from src.tools.database import save_snapshot

# Step 1: Load config
print("=" * 60)
print("STEP 1: Loading config")
print("=" * 60)
config = load_config()
tickers = [h["ticker"] for h in config["holdings"]]
print(f"  Budget: ${config['budget']['monthly_amount']}")
print(f"  Holdings: {tickers}")

# Step 2: Fetch live prices
print()
print("=" * 60)
print("STEP 2: Fetching live prices")
print("=" * 60)
prices = get_current_prices(tickers)
for t, p in prices.items():
    print(f"  {t}: ${p}")

# Step 3: Build portfolio state
print()
print("=" * 60)
print("STEP 3: Portfolio state")
print("=" * 60)
portfolio = build_portfolio_state(
    config["holdings"],
    config["target_allocation"],
    prices,
)
print(f"  Total value:  ${portfolio.total_value:,.2f}")
print(f"  Total cost:   ${portfolio.total_cost:,.2f}")
print(f"  Total return: {portfolio.total_return_pct:+.1f}%")

# Step 4: Drift analysis
print()
print("=" * 60)
print("STEP 4: Allocation drift")
print("=" * 60)
print(f"  {'Ticker':<8} {'Target':>8} {'Actual':>8} {'Drift':>8}  Status")
print(f"  {'─'*8} {'─'*8} {'─'*8} {'─'*8}  {'─'*14}")
for h in sorted(portfolio.holdings, key=lambda x: x.drift):
    if h.drift < -2:
        status = "UNDERWEIGHT"
    elif h.drift > 2:
        status = "OVERWEIGHT"
    else:
        status = "On target"
    print(f"  {h.ticker:<8} {h.target_pct:>7.1f}% {h.actual_pct:>7.1f}% {h.drift:>+7.1f}%  {status}")

# Step 5: Score each ticker
print()
print("=" * 60)
print("STEP 5: Market scores")
print("=" * 60)
scores = {}
for t in tickers:
    s = analyze_ticker(t)
    scores[t] = s
    bar = "#" * s.score + "." * (10 - s.score)
    print(f"  {t:<8} [{bar}] {s.score}/10  {s.reasoning}")

# Step 6: VIX
print()
print("=" * 60)
print("STEP 6: Market mood")
print("=" * 60)
vix = get_vix()
print(f"  VIX: {vix['vix']} | Mood: {vix['mood']}")

# Step 7: Deployment plan (DOLLAR BASED)
print()
print("=" * 60)
print("STEP 7: DEPLOYMENT PLAN (Dollar-Based)")
print("=" * 60)
plan = generate_deployment_plan(
    portfolio=portfolio,
    scores=scores,
    budget=config["budget"]["monthly_amount"],
    max_single_pct=config["budget"]["max_single_position_pct"],
)

print(f"  Strategy: {plan.strategy}")
print(f"  Budget:   ${plan.budget:,.2f}")
print()

if plan.recommendations:
    print(f"  {'Ticker':<8} {'Amount':>10} {'% Budget':>10}  Reasoning")
    print(f"  {'─'*8} {'─'*10} {'─'*10}  {'─'*35}")
    for r in plan.recommendations:
        print(f"  {r.ticker:<8} ${r.dollar_amount:>8,.0f} {r.pct_of_budget:>9.1f}%  {r.reasoning}")

    print()
    total = sum(r.dollar_amount for r in plan.recommendations)
    print(f"  Total deployed: ${total:,.0f}")
    print(f"  Cash remaining: ${plan.cash_remaining:,.0f}")
    print()
    print("  ┌──────────────────────────────────────────────┐")
    print("  │  HOW TO EXECUTE IN FIDELITY:                 │")
    print("  │                                              │")
    for r in plan.recommendations:
        line = f"  │  → Buy ${r.dollar_amount:,.0f} of {r.ticker}"
        print(f"{line:<49}│")
    print("  │                                              │")
    print("  │  That's it. Fidelity handles fractional      │")
    print("  │  shares automatically.                       │")
    print("  └──────────────────────────────────────────────┘")
else:
    print("  No recommendations. All positions overweight.")

# Step 8: Save snapshot
print()
print("=" * 60)
print("STEP 8: Snapshot saved to database")
print("=" * 60)
save_snapshot(
    total_value=portfolio.total_value,
    total_cost=portfolio.total_cost,
    holdings=[h.model_dump() for h in portfolio.holdings],
)
print("  Saved to data/portfolio.db")

print()
print("=" * 60)
print("CORE ENGINE COMPLETE")
print("=" * 60)