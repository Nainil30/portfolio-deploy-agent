# src/utils/config_loader.py
"""
Loads the YAML config and validates it.

WHY THIS EXISTS:
Every part of the app needs config data (budget, holdings, targets).
Instead of each file reading YAML independently, they all call
load_config() from here. One place to load, one place to validate.
"""

from pathlib import Path
from typing import Any
import yaml

# Navigate from this file to project root
# This file is at: src/utils/config_loader.py
# Project root is: ../../ from here
PROJECT_ROOT = Path(__file__).parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "portfolio_config.yaml"
DB_PATH = PROJECT_ROOT / "data" / "portfolio.db"


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Load YAML config and validate it."""
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")

    with open(path) as f:
        config = yaml.safe_load(f)

    _validate(config)
    return config


def _validate(config: dict) -> None:
    """Catch config errors early with clear messages."""
    # Allocation must sum to 100
    targets = config.get("target_allocation", {})
    total = sum(targets.values())
    if abs(total - 100) > 0.01:
        raise ValueError(f"target_allocation sums to {total}, must be 100")

    # Every holding needs a matching target
    holding_tickers = {h["ticker"] for h in config.get("holdings", [])}
    target_tickers = set(targets.keys())
    missing = holding_tickers - target_tickers
    if missing:
        raise ValueError(f"Holdings without targets: {missing}")

    # Budget must be positive
    budget = config.get("budget", {}).get("monthly_amount", 0)
    if budget <= 0:
        raise ValueError("budget.monthly_amount must be positive")
