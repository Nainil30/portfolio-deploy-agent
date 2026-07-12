# src/utils/config_loader.py
# src/utils/config_loader.py
"""
Loads the YAML config and validates it.
Supports two allocation modes:
  1. category_targets: {etf: 60, stocks: 30, gold: 10}
  2. target_allocation: {VOO: 25, QQQM: 15, ...}

If category_targets is used, ticker-level targets are auto-generated
by splitting each category's % equally among its tickers.
"""

from pathlib import Path
from typing import Any
import yaml

PROJECT_ROOT = Path(__file__).parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "portfolio_config.yaml"
DB_PATH = PROJECT_ROOT / "data" / "portfolio.db"


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Load YAML config, resolve category targets, and validate."""
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")

    with open(path) as f:
        config = yaml.safe_load(f)

    # If user provided category_targets, convert to ticker-level
    if "category_targets" in config and "target_allocation" not in config:
        config["target_allocation"] = _resolve_category_targets(config)

    _validate(config)
    return config


def _resolve_category_targets(config: dict) -> dict[str, float]:
    """
    Convert category-level targets to ticker-level targets.

    EXAMPLE:
      category_targets: {etf: 60, stocks: 30, gold: 10}
      holdings with categories:
        VOO(etf), QQQM(etf), SPMO(etf), SCHD(etf),
        AAPL(stocks), MSFT(stocks), AMZN(stocks),
        GLD(gold)

    RESULT:
      VOO: 15, QQQM: 15, SPMO: 15, SCHD: 15  (60/4 each)
      AAPL: 10, MSFT: 10, AMZN: 10            (30/3 each)
      GLD: 10                                   (10/1)

    WHY EQUAL SPLIT WITHIN CATEGORY:
    If the user wanted different weights per ticker,
    they would use ticker-level targets directly.
    Category mode means "I don't care about individual
    weights, just keep the buckets balanced."
    """
    cat_targets = config["category_targets"]
    holdings = config.get("holdings", [])

    # Group tickers by category
    category_tickers: dict[str, list[str]] = {}
    for h in holdings:
        cat = h.get("category", "other")
        if cat not in category_tickers:
            category_tickers[cat] = []
        category_tickers[cat].append(h["ticker"])

    # Split each category's % equally among its tickers
    ticker_targets = {}
    for cat, pct in cat_targets.items():
        tickers_in_cat = category_tickers.get(cat, [])
        if not tickers_in_cat:
            print(f"  Warning: category '{cat}' has {pct}% target but no holdings")
            continue
        per_ticker = round(pct / len(tickers_in_cat), 2)
        for t in tickers_in_cat:
            ticker_targets[t] = per_ticker

    # Handle tickers with no category target
    for h in holdings:
        if h["ticker"] not in ticker_targets:
            ticker_targets[h["ticker"]] = 0.0
            print(f"  Warning: {h['ticker']} has no category target, set to 0%")

    return ticker_targets


def _validate(config: dict) -> None:
    """Catch config errors early with clear messages."""
    targets = config.get("target_allocation", {})
    total = sum(targets.values())
    if abs(total - 100) > 1.0:  # Allow small rounding from category split
        raise ValueError(f"target_allocation sums to {total}, must be ~100")

    holding_tickers = {h["ticker"] for h in config.get("holdings", [])}
    target_tickers = set(targets.keys())
    missing = holding_tickers - target_tickers
    if missing:
        raise ValueError(f"Holdings without targets: {missing}")

    budget = config.get("budget", {}).get("monthly_amount", 0)
    if budget <= 0:
        raise ValueError("budget.monthly_amount must be positive")