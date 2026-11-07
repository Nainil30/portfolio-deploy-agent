"""Load and validate strategy.yaml.

Validation is strict on purpose: a typo in an investing plan should stop the
bot loudly at startup, not silently produce a wrong buy list.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from pda.models import TargetSpec

PROJECT_ROOT = Path(os.getenv("PDA_HOME", Path(__file__).resolve().parents[2]))
CONFIG_DIR = PROJECT_ROOT / "config"
DEFAULT_STRATEGY = Path(os.getenv("PDA_STRATEGY", CONFIG_DIR / "strategy.yaml"))
DEFAULT_DB = Path(os.getenv("PDA_DB", PROJECT_ROOT / "data" / "pda.db"))
DEMO_PRICES = CONFIG_DIR / "demo_prices.yaml"

VALID_BUCKETS = {"core_etf", "etf", "gold", "stock"}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Guardrails:
    never_sell: bool
    core_ticker: str
    core_versus: str
    core_min_multiple: float
    max_single_stock_pct: float
    per_ticker_caps: dict[str, float]
    cushions: tuple[str, ...]
    overflow_ticker: str

    def cap_for(self, spec: TargetSpec | None, ticker: str) -> float | None:
        """Max % of portfolio this ticker may reach through buying, or None if uncapped."""
        if ticker in self.per_ticker_caps:
            return self.per_ticker_caps[ticker]
        if spec is not None and spec.bucket == "stock":
            return self.max_single_stock_pct
        return None


@dataclass(frozen=True)
class Strategy:
    goal_value: float
    expected_return: float
    monthly_amount: float
    reminder_day: int
    reminder_time: time
    daily_check_time: time
    timezone: ZoneInfo
    min_buy: float
    split: dict[str, float]
    slot_amount: float
    slot_candidates: tuple[str, ...]
    targets: dict[str, TargetSpec]
    guardrails: Guardrails
    drawdown_levels: tuple[float, ...]
    weekly_digest: bool
    yahoo_aliases: dict[str, str] = field(default_factory=dict)

    def spec(self, ticker: str) -> TargetSpec | None:
        return self.targets.get(ticker)


def normalize_ticker(raw: str) -> str:
    """'brk/b', 'BRK-B', 'brkb' -> 'BRK.B'. Everything else upper-cased and trimmed."""
    t = raw.strip().upper().lstrip("$")
    t = t.replace("/", ".").replace("-", ".")
    if t == "BRKB":
        t = "BRK.B"
    if t == "BRKA":
        t = "BRK.A"
    return t


def _parse_time(value: str, where: str) -> time:
    try:
        hh, mm = str(value).split(":")
        return time(int(hh), int(mm))
    except Exception as exc:  # noqa: BLE001
        raise ConfigError(f"{where}: expected HH:MM, got {value!r}") from exc


def load_strategy(path: Path | str = DEFAULT_STRATEGY) -> Strategy:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"Strategy file not found: {path}")
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return parse_strategy(raw)


def parse_strategy(raw: dict) -> Strategy:
    try:
        goal = raw["goal"]
        monthly = raw["monthly"]
        g = raw["guardrails"]
        targets_raw = raw["targets"]
    except KeyError as exc:
        raise ConfigError(f"strategy.yaml is missing section {exc}") from exc

    tz_name = monthly.get("timezone", "America/New_York")
    try:
        tz = ZoneInfo(tz_name)
    except Exception as exc:  # noqa: BLE001
        raise ConfigError(f"Unknown timezone {tz_name!r}") from exc

    targets: dict[str, TargetSpec] = {}
    for raw_t, spec in targets_raw.items():
        t = normalize_ticker(raw_t)
        bucket = spec.get("bucket", "stock")
        if bucket not in VALID_BUCKETS:
            raise ConfigError(f"targets.{t}: bucket must be one of {sorted(VALID_BUCKETS)}")
        targets[t] = TargetSpec(t, float(spec["pct"]), bucket, bool(spec.get("ai", False)))

    slot = monthly.get("stock_slot", {}) or {}
    alerts = raw.get("alerts", {}) or {}
    core = g.get("core_ratio", {}) or {}

    strategy = Strategy(
        goal_value=float(goal["target_value"]),
        expected_return=float(goal.get("expected_annual_return", 0.07)),
        monthly_amount=float(monthly["amount"]),
        reminder_day=int(monthly.get("reminder_day", 1)),
        reminder_time=_parse_time(monthly.get("reminder_time", "09:30"), "monthly.reminder_time"),
        daily_check_time=_parse_time(alerts.get("daily_check_time", "16:30"), "alerts.daily_check_time"),
        timezone=tz,
        min_buy=float(monthly.get("min_buy", 25)),
        split={normalize_ticker(k): float(v) for k, v in (monthly.get("split") or {}).items()},
        slot_amount=float(slot.get("amount", 0)),
        slot_candidates=tuple(normalize_ticker(c) for c in slot.get("candidates", [])),
        targets=targets,
        guardrails=Guardrails(
            never_sell=bool(g.get("never_sell", True)),
            core_ticker=normalize_ticker(core.get("ticker", "VOO")),
            core_versus=normalize_ticker(core.get("versus", "QQQM")),
            core_min_multiple=float(core.get("min_multiple", 3.0)),
            max_single_stock_pct=float(g.get("max_single_stock_pct", 5.0)),
            per_ticker_caps={normalize_ticker(k): float(v) for k, v in (g.get("per_ticker_caps") or {}).items()},
            cushions=tuple(normalize_ticker(c) for c in g.get("cushions", [])),
            overflow_ticker=normalize_ticker(g.get("overflow_ticker", "VOO")),
        ),
        drawdown_levels=tuple(sorted(float(x) for x in alerts.get("drawdown_levels_pct", [10, 20, 30]))),
        weekly_digest=bool(alerts.get("weekly_digest", True)),
        yahoo_aliases={normalize_ticker(k): v for k, v in (raw.get("yahoo_aliases") or {}).items()},
    )
    validate(strategy)
    return strategy


def validate(s: Strategy) -> None:
    errors: list[str] = []

    total = sum(t.pct for t in s.targets.values())
    if abs(total - 100.0) > 0.01:
        errors.append(f"targets add up to {total:.2f}%, must be exactly 100%")

    if not 1 <= s.reminder_day <= 28:
        errors.append("monthly.reminder_day must be 1–28 so it exists in every month")

    split_total = sum(s.split.values()) + s.slot_amount
    if abs(split_total - s.monthly_amount) > 0.01:
        errors.append(
            f"monthly.split + stock_slot = ${split_total:,.0f}, but monthly.amount = ${s.monthly_amount:,.0f}"
        )

    for t in list(s.split) + list(s.slot_candidates):
        if t not in s.targets:
            errors.append(f"{t} is bought monthly but has no entry in targets")

    g = s.guardrails
    for t in (g.core_ticker, g.core_versus, g.overflow_ticker, *g.cushions):
        if t not in s.targets:
            errors.append(f"guardrails reference {t}, which has no entry in targets")

    for t, cap in g.per_ticker_caps.items():
        spec = s.targets.get(t)
        if spec and spec.pct > cap:
            errors.append(f"{t} target {spec.pct}% is above its own cap {cap}%")
    for spec in s.targets.values():
        cap = g.cap_for(spec, spec.ticker)
        if cap is not None and spec.pct > cap:
            errors.append(f"{spec.ticker} target {spec.pct}% exceeds the single-stock cap {cap}%")

    # The written plan itself must satisfy "VHT and BRK.B are the biggest non-AI buys".
    cushion_min = min((s.split.get(c, 0.0) for c in g.cushions), default=0.0)
    for t, amt in s.split.items():
        spec = s.targets.get(t)
        if not spec or spec.ai or spec.bucket == "core_etf" or t in g.cushions:
            continue
        if amt > cushion_min:
            errors.append(
                f"monthly.split: {t} (${amt:,.0f}) is a bigger non-AI buy than the cushions "
                f"{', '.join(g.cushions)} (min ${cushion_min:,.0f})"
            )

    if errors:
        raise ConfigError("Invalid strategy.yaml:\n  - " + "\n  - ".join(errors))
