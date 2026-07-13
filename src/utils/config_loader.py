# src/utils/config_loader.py
"""
Loads the YAML config and validates it.
"""

from pathlib import Path
from typing import Any
import yaml

PROJECT_ROOT = Path(__file__).parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "portfolio_config.yaml"
EXAMPLE_CONFIG_PATH = PROJECT_ROOT / "config" / "portfolio_config.example.yaml"
DB_PATH = PROJECT_ROOT / "data" / "portfolio.db"


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Load YAML config, resolve category targets, and validate."""
    if path.exists():
        config_file = path
    elif EXAMPLE_CONFIG_PATH.exists():
        print("   Using example config. Copy and edit your own:")
        print(f"   cp {EXAMPLE_CONFIG_PATH} {CONFIG_PATH}")
        config_file = EXAMPLE_CONFIG_PATH
    else:
        raise FileNotFoundError(
            f"No config found. Create {CONFIG_PATH} from the example."
        )

    with open(config_file, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if "category_targets" in config and "target_allocation" not in config:
        config["target_allocation"] = _resolve_category_targets(config)

    _validate(config)
    return config


def _resolve_category_targets(config: dict) -> dict[str, float]:
    """Convert category-level targets to ticker-level targets."""
    cat_targets = config["category_targets"]
    holdings = config.get("holdings", [])

    category_tickers: dict[str, list[str]] = {}
    for h in holdings:
        cat = h.get("category", "other")
        if cat not in category_tickers:
            category_tickers[cat] = []
        category_tickers[cat].append(h["ticker"])

    ticker_targets = {}
    for cat, pct in cat_targets.items():
        tickers_in_cat = category_tickers.get(cat, [])
        if not tickers_in_cat:
            continue
        per_ticker = round(pct / len(tickers_in_cat), 2)
        for t in tickers_in_cat:
            ticker_targets[t] = per_ticker

    for h in holdings:
        if h["ticker"] not in ticker_targets:
            ticker_targets[h["ticker"]] = 0.0

    return ticker_targets


def _validate(config: dict) -> None:
    """Catch config errors early with clear messages."""
    targets = config.get("target_allocation", {})
    total = sum(targets.values())
    if abs(total - 100) > 1.0:
        raise ValueError(f"target_allocation sums to {total}, must be ~100")

    holding_tickers = {h["ticker"] for h in config.get("holdings", [])}
    target_tickers = set(targets.keys())
    missing = holding_tickers - target_tickers
    if missing:
        raise ValueError(f"Holdings without targets: {missing}")

    budget = config.get("budget", {}).get("monthly_amount", 0)
    if budget <= 0:
        raise ValueError("budget.monthly_amount must be positive")