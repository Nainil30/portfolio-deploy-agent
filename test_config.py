# test_config.py
"""Test that category-based config resolves correctly."""

from src.utils.config_loader import load_config

config = load_config()

print("=" * 60)
print("CONFIG LOADED SUCCESSFULLY")
print("=" * 60)

# Show category targets if present
if "category_targets" in config:
    print("\nCategory Targets (what you set):")
    for cat, pct in config["category_targets"].items():
        print(f"  {cat}: {pct}%")

# Show resolved ticker targets
print("\nResolved Ticker Targets (auto-calculated):")
for ticker, pct in config["target_allocation"].items():
    # Find category for this ticker
    cat = "?"
    for h in config["holdings"]:
        if h["ticker"] == ticker:
            cat = h.get("category", "?")
            break
    print(f"  {ticker:<8} → {pct:>6.2f}%  (category: {cat})")

total = sum(config["target_allocation"].values())
print(f"\n  Total: {total}%")
print(f"  Budget: ${config['budget']['monthly_amount']}")