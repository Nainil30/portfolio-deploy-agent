# test_full_pipeline.py
"""
Full pipeline test: config → prices → portfolio → deployment plan.
This is the entire core engine running end to end.
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
print(f"  Holdings: {len(tickers)} tickers → {tickers}")

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
print("STEP 4: Allocation drift analysis")
print("=" * 60)
print(f"  {'Ticker':<8} {'Target':>8} {'Actual':>8} {'Drift':>8}  Status")
print(f"  {'-'*8} {'-'*8} {'-'*8} {'-'*8}  {'-'*12}")
for h in sorted(portfolio.holdings, key=lambda x: x.drift):
    if h.drift < -2:
        status = "🔴 UNDERWEIGHT"
    elif h.drift > 2:
        status = "🟡 OVERWEIGHT"
    else:
        status = "🟢 On target"
    print(f"  {h.ticker:<8} {h.target_pct:>7.1f}% {h.actual_pct:>7.1f}% {h.drift:>+7.1f}%  {status}")

# Step 5: Score each ticker
print()
print("=" * 60)
print("STEP 5: Market attractiveness scores")
print("=" * 60)
scores = {}
for t in tickers:
    s = analyze_ticker(t)
    scores[t] = s
    bar = "█" * s.score + "░" * (10 - s.score)
    print(f"  {t:<8} [{bar}] {s.score}/10  {s.reasoning}")

# Step 6: VIX check
print()
print("=" * 60)
print("STEP 6: Market mood (VIX)")
print("=" * 60)
vix = get_vix()
print(f"  VIX: {vix['vix']} → Mood: {vix['mood']}")

# Step 7: Generate deployment plan
print()
print("=" * 60)
print("STEP 7: Deployment recommendation")
print("=" * 60)
plan = generate_deployment_plan(
    portfolio=portfolio,
    scores=scores,
    budget=config["budget"]["monthly_amount"],
    max_single_pct=config["budget"]["max_single_position_pct"],
)

print(f"  Budget:   ${plan.budget:,.2f}")
print(f"  Strategy: {plan.strategy}")
print()
if plan.recommendations:
    print(f"  {'Ticker':<8} {'Shares':>8} {'Cost':>10}  Reasoning")
    print(f"  {'-'*8} {'-'*8} {'-'*10}  {'-'*25}")
    for r in plan.recommendations:
        print(f"  {r.ticker:<8} {r.shares_to_buy:>8} {r.estimated_cost:>9,.2f}  {r.reasoning}")
    print()
    total_spent = sum(r.estimated_cost for r in plan.recommendations)
    print(f"  Total spent:    ${total_spent:,.2f}")
    print(f"  Cash remaining: ${plan.cash_remaining:,.2f}")
else:
    print("  No buy recommendations. All positions overweight or budget too small.")

# Step 8: Save snapshot
print()
print("=" * 60)
print("STEP 8: Saving portfolio snapshot to database")
print("=" * 60)
save_snapshot(
    total_value=portfolio.total_value,
    total_cost=portfolio.total_cost,
    holdings=[h.model_dump() for h in portfolio.holdings],
)
print("  Saved to data/portfolio.db")

print()
print("=" * 60)
print("CORE ENGINE TEST COMPLETE")
print("=" * 60)