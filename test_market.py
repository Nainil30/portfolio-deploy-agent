# test_market.py
"""
Quick test: does market data fetching work?
Run with: python test_market.py
Delete this file whenever you want — it is just for testing.
"""

from src.tools.market_data import get_current_prices, analyze_ticker, get_vix

print("=" * 50)
print("TEST 1: Fetching prices")
print("=" * 50)
prices = get_current_prices(["VOO", "QQQM", "GLD"])
for ticker, price in prices.items():
    print(f"  {ticker}: ${price}")

print()
print("=" * 50)
print("TEST 2: Analyzing VOO")
print("=" * 50)
score = analyze_ticker("VOO")
print(f"  Price:    ${score.current_price}")
print(f"  SMA 20:  ${score.sma_20}")
print(f"  RSI:     {score.rsi}")
print(f"  Drawdown: {score.drawdown_from_high_pct}%")
print(f"  Red days: {score.consecutive_red_days}")
print(f"  Score:   {score.score}/10")
print(f"  Reason:  {score.reasoning}")

print()
print("=" * 50)
print("TEST 3: VIX (market fear)")
print("=" * 50)
vix = get_vix()
print(f"  VIX:  {vix['vix']}")
print(f"  Mood: {vix['mood']}")

print()
print("ALL TESTS PASSED")