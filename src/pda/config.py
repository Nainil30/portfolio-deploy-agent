"""Load and validate a strategy file (config/strategy.yaml).

Anyone can describe their own plan: a monthly amount, target tickers with
weights, a money goal, and optional guardrails. Validation is strict on
purpose: a typo in an investing plan should stop the bot loudly at
startup, not silently produce a wrong buy list.

Two monthly modes:
  auto   – every month's money goes to whatever is furthest below target
           (rebalance with new money). Easiest: just list targets.
  fixed  – a written dollar split (+ an optional "stock slot" that goes to
           the candidate furthest below target), then guardrails.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, replace
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from pda.models import TargetSpec

PROJECT_ROOT = Path(os.getenv("PDA_HOME", Path(__file__).resolve().parents[2]))
CONFIG_DIR = PROJECT_ROOT / "config"
EXAMPLES_DIR = PROJECT_ROOT / "examples"
DEFAULT_STRATEGY = Path(os.getenv("PDA_STRATEGY", CONFIG_DIR / "strategy.yaml"))
DEFAULT_DB = Path(os.getenv("PDA_DB", PROJECT_ROOT / "data" / "pda.db"))
DEMO_PRICES = CONFIG_DIR / "demo_prices.yaml"
DEMO_STRATEGY = EXAMPLES_DIR / "core_plus_stock_slot.yaml"
DEMO_HOLDINGS = EXAMPLES_DIR / "holdings.example.yaml"

VALID_BUCKETS = {"core_etf", "etf", "stock", "bond", "gold", "reit", "crypto", "cash"}
SETTABLE = {"monthly_amount", "goal_value", "reminder_day", "expected_return"}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Guardrails:
    never_sell: bool = True
    max_single_stock_pct: float | None = None
    per_ticker_caps: dict[str, float] = field(default_factory=dict)
    core_ticker: str | None = None      # e.g. VOO must stay >= min_multiple x ...
    core_versus: str | None = None      # ... QQQM
    core_min_multiple: float = 3.0
    cushions: tuple[str, ...] = ()      # must be the biggest non-theme buys
    overflow_ticker: str = ""

    @property
    def has_core_ratio(self) -> bool:
        return bool(self.core_ticker and self.core_versus)

    def cap_for(self, spec: TargetSpec | None, ticker: str) -> float | None:
        """Max % of portfolio this ticker may reach through buying, or None if uncapped."""
        if ticker in self.per_ticker_caps:
            return self.per_ticker_caps[ticker]
        if spec is not None and spec.bucket == "stock":
            return self.max_single_stock_pct
        return None


@dataclass(frozen=True)
class Strategy:
    name: str
    currency: str
    goal_value: float
    expected_return: float
    mode: str  # "auto" | "fixed"
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

    @property
    def split_base(self) -> float:
        """What the written split adds up to (the amount it was designed for)."""
        return sum(self.split.values()) + self.slot_amount

    @property
    def has_theme(self) -> bool:
        return any(t.ai for t in self.targets.values())

    def with_overrides(self, overrides: dict[str, str]) -> Strategy:
        """Apply settings changed from Telegram (/set monthly 3000)."""
        kw: dict = {}
        for k, v in overrides.items():
            if k not in SETTABLE:
                continue
            kw[k] = int(float(v)) if k == "reminder_day" else float(v)
        return replace(self, **kw) if kw else self


_CLASS_SHARE = re.compile(r"^[A-Z]{1,5}[.-][A-Z]$")


def normalize_ticker(raw: str) -> str:
    """Canonical form: upper-case; 'brk/b', 'BRK-B', 'brkb' -> 'BRK.B'.

    Exchange suffixes ('RELIANCE.NS', 'SHOP.TO') and crypto pairs ('BTC-USD')
    are kept as they are.
    """
    t = raw.strip().upper().lstrip("$").replace("/", ".")
    if _CLASS_SHARE.match(t):
        t = t.replace("-", ".")
    if t in ("BRKB", "BRKA"):
        t = t[:3] + "." + t[3]
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
        raise ConfigError(
            f"No strategy found at {path}.\n"
            "  Run `pda init` to create one in a minute, or copy a preset:\n"
            f"  cp examples/three_fund.yaml {path}"
        )
    with open(path, encoding="utf-8") as f:
        try:
            raw = yaml.safe_load(f) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"{path} is not valid YAML: {exc}") from exc
    return parse_strategy(raw)


def parse_strategy(raw: dict) -> Strategy:
    if not isinstance(raw, dict):
        raise ConfigError("strategy file must be a YAML mapping")
    try:
        goal = raw["goal"]
        monthly = raw["monthly"]
        targets_raw = raw["targets"]
    except KeyError as exc:
        raise ConfigError(f"strategy is missing the section {exc}") from exc
    g = raw.get("guardrails") or {}
    profile = raw.get("profile") or {}

    tz_name = monthly.get("timezone", "America/New_York")
    try:
        tz = ZoneInfo(tz_name)
    except Exception as exc:  # noqa: BLE001
        raise ConfigError(f"Unknown timezone {tz_name!r} (use e.g. America/New_York, Europe/London, Asia/Kolkata)") from exc

    targets: dict[str, TargetSpec] = {}
    for raw_t, spec in (targets_raw or {}).items():
        t = normalize_ticker(str(raw_t))
        if isinstance(spec, (int, float)):  # shorthand:  VTI: 60
            spec = {"pct": spec}
        bucket = spec.get("bucket", "etf")
        if bucket not in VALID_BUCKETS:
            raise ConfigError(f"targets.{t}: bucket must be one of {sorted(VALID_BUCKETS)}")
        targets[t] = TargetSpec(t, float(spec["pct"]), bucket, bool(spec.get("ai", spec.get("theme", False))))
    if not targets:
        raise ConfigError("targets is empty: list at least one ticker with a % weight")

    split = {normalize_ticker(str(k)): float(v) for k, v in (monthly.get("split") or {}).items()}
    slot = monthly.get("stock_slot") or {}
    mode = monthly.get("mode") or ("fixed" if split else "auto")
    core = g.get("core_ratio") or {}
    alerts = raw.get("alerts") or {}
    largest = max(targets.values(), key=lambda s: s.pct).ticker
    max_stock = g.get("max_single_stock_pct", 10.0)

    strategy = Strategy(
        name=str(profile.get("name", "My plan")),
        currency=str(profile.get("currency", "$")),
        goal_value=float(goal["target_value"]),
        expected_return=float(goal.get("expected_annual_return", 0.07)),
        mode=mode,
        monthly_amount=float(monthly["amount"]),
        reminder_day=int(monthly.get("reminder_day", 1)),
        reminder_time=_parse_time(monthly.get("reminder_time", "09:30"), "monthly.reminder_time"),
        daily_check_time=_parse_time(alerts.get("daily_check_time", "16:30"), "alerts.daily_check_time"),
        timezone=tz,
        min_buy=float(monthly.get("min_buy", 25)),
        split=split,
        slot_amount=float(slot.get("amount", 0)),
        slot_candidates=tuple(normalize_ticker(str(c)) for c in slot.get("candidates", [])),
        targets=targets,
        guardrails=Guardrails(
            never_sell=bool(g.get("never_sell", True)),
            max_single_stock_pct=None if max_stock is None else float(max_stock),
            per_ticker_caps={normalize_ticker(str(k)): float(v) for k, v in (g.get("per_ticker_caps") or {}).items()},
            core_ticker=normalize_ticker(core["ticker"]) if core.get("ticker") else None,
            core_versus=normalize_ticker(core["versus"]) if core.get("versus") else None,
            core_min_multiple=float(core.get("min_multiple", 3.0)),
            cushions=tuple(normalize_ticker(str(c)) for c in g.get("cushions", []) or []),
            overflow_ticker=normalize_ticker(str(g.get("overflow_ticker") or largest)),
        ),
        drawdown_levels=tuple(sorted(float(x) for x in alerts.get("drawdown_levels_pct", [10, 20, 30]))),
        weekly_digest=bool(alerts.get("weekly_digest", True)),
        yahoo_aliases={normalize_ticker(str(k)): v for k, v in (raw.get("yahoo_aliases") or {}).items()},
    )
    validate(strategy)
    return strategy


def validate(s: Strategy) -> None:
    errors: list[str] = []
    g = s.guardrails

    total = sum(t.pct for t in s.targets.values())
    if abs(total - 100.0) > 0.01:
        errors.append(f"targets add up to {total:.2f}%, must be exactly 100%")
    for t in s.targets.values():
        if t.pct < 0:
            errors.append(f"{t.ticker}: target % can't be negative")
    if s.monthly_amount <= 0:
        errors.append("monthly.amount must be positive")
    if s.goal_value <= 0:
        errors.append("goal.target_value must be positive")
    if not 1 <= s.reminder_day <= 28:
        errors.append("monthly.reminder_day must be 1–28 so it exists in every month")
    if not -0.5 < s.expected_return < 0.5:
        errors.append("goal.expected_annual_return looks wrong; use a decimal like 0.07 for 7%")

    if s.mode not in ("auto", "fixed"):
        errors.append("monthly.mode must be 'auto' or 'fixed'")
    elif s.mode == "auto":
        if s.split or s.slot_amount:
            errors.append("monthly.mode is 'auto': remove split/stock_slot, or set mode: fixed")
    else:
        if not s.split and not s.slot_amount:
            errors.append("monthly.mode is 'fixed' but no split was given")
        if abs(s.split_base - s.monthly_amount) > 0.01:
            errors.append(
                f"monthly.split + stock_slot = {s.split_base:,.0f}, but monthly.amount = {s.monthly_amount:,.0f}"
            )
        if s.slot_amount and not s.slot_candidates:
            errors.append("stock_slot has an amount but no candidates")
        for t in list(s.split) + list(s.slot_candidates):
            if t not in s.targets:
                errors.append(f"{t} is bought monthly but has no entry in targets")

    refs = [g.overflow_ticker, *g.cushions]
    if g.has_core_ratio:
        refs += [g.core_ticker, g.core_versus]
    elif g.core_ticker or g.core_versus:
        errors.append("guardrails.core_ratio needs both ticker and versus")
    for t in refs:
        if t not in s.targets:
            errors.append(f"guardrails reference {t}, which has no entry in targets")
    if g.has_core_ratio and g.core_min_multiple <= 0:
        errors.append("core_ratio.min_multiple must be positive")

    for spec in s.targets.values():
        cap = g.cap_for(spec, spec.ticker)
        if cap is not None and spec.pct > cap:
            errors.append(f"{spec.ticker} target {spec.pct:g}% is above its cap {cap:g}% (raise per_ticker_caps or lower the target)")

    # In fixed mode, the written split itself must respect the cushion rule.
    if s.mode == "fixed" and g.cushions:
        cushion_min = min(s.split.get(c, 0.0) for c in g.cushions)
        for t, amt in s.split.items():
            spec = s.targets.get(t)
            if not spec or spec.ai or spec.bucket == "core_etf" or t in g.cushions:
                continue
            if amt > cushion_min:
                errors.append(
                    f"monthly.split: {t} ({amt:,.0f}) is a bigger non-theme buy than the cushions "
                    f"{', '.join(g.cushions)} (min {cushion_min:,.0f})"
                )

    if errors:
        raise ConfigError("Invalid strategy:\n  - " + "\n  - ".join(errors))
