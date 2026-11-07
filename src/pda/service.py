"""Service facade: the one object the bot, CLI, LLM tools and dashboard talk to.

Keeping every interface on the same facade means "what Telegram shows" and
"what the CLI prints" can never disagree.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from pda.config import Strategy, normalize_ticker
from pda.engine import extra_plan, monthly_plan
from pda.guardrails import check_portfolio
from pda.importers import parse_file
from pda.insights import Drawdown, Projection, StressResult, project, stress_test
from pda.ledger import Ledger, LedgerError, Tx
from pda.models import Plan, RuleCheck, Snapshot
from pda.portfolio import build_snapshot
from pda.prices import PriceProvider


class ServiceError(ValueError):
    """User-facing error with a message safe to show in chat."""


@dataclass
class Recorded:
    batch: str
    rows: list[tuple[str, float, float, float]]  # ticker, shares, price, amount
    warnings: list[str]


class Service:
    def __init__(self, strategy: Strategy, ledger: Ledger, prices: PriceProvider):
        self.strategy = strategy
        self.ledger = ledger
        self.prices = prices

    # ── read side ──────────────────────────────────────────────────────
    def snapshot(self, save: bool = True) -> Snapshot:
        holdings = self.ledger.holdings()
        tickers = sorted(set(self.strategy.targets) | set(holdings))
        snap = build_snapshot(holdings, self.strategy, self.prices.get_prices(tickers))
        if save and snap.total_value > 0 and not snap.missing_prices:
            self.ledger.save_snapshot(date.today(), snap.total_value, snap.total_cost)
        return snap

    def guardrails(self, snap: Snapshot | None = None) -> list[RuleCheck]:
        return check_portfolio(snap or self.snapshot(), self.strategy, self.ledger.sell_count())

    def goal(self, snap: Snapshot | None = None, monthly: float | None = None) -> list[Projection]:
        snap = snap or self.snapshot()
        return project(
            snap.total_value, monthly or self.strategy.monthly_amount,
            self.strategy.goal_value, self.strategy.expected_return,
        )

    def stress(self, snap: Snapshot | None = None) -> list[StressResult]:
        return stress_test(snap or self.snapshot())

    def history(self, limit: int = 15) -> list[Tx]:
        return self.ledger.recent(limit)

    def drawdown(self, snap: Snapshot) -> Drawdown | None:
        peak = self.ledger.peak()
        if not peak:
            return None
        return Drawdown(peak[0], peak[1], snap.gain)

    def new_drawdown_alert(self, snap: Snapshot) -> tuple[float, Drawdown] | None:
        """Return (level, drawdown) the first time a drawdown level is crossed since the last peak."""
        dd = self.drawdown(snap)
        if not dd or dd.dollars <= 0:
            return None
        pct = dd.pct(snap.total_cost)
        crossed = [lvl for lvl in self.strategy.drawdown_levels if pct >= lvl]
        if not crossed:
            return None
        level = max(crossed)
        key = f"dd:{dd.peak_day}:{level:g}"
        if self.ledger.alert_sent(key):
            return None
        self.ledger.mark_alert(key)
        return level, dd

    def month_done(self) -> bool:
        return self.ledger.monthly_plan_executed(datetime.now().strftime("%Y-%m"))

    # ── plans ──────────────────────────────────────────────────────────
    def plan(self, amount: float | None = None) -> tuple[Plan, Snapshot]:
        snap = self.snapshot()
        plan = monthly_plan(snap, self.strategy, amount)
        self.ledger.save_plan(plan)
        return plan, snap

    def extra(self, cash: float) -> tuple[Plan, Snapshot]:
        snap = self.snapshot()
        plan = extra_plan(snap, self.strategy, cash)
        self.ledger.save_plan(plan)
        return plan, snap

    def execute_plan(self, plan_id: int) -> Recorded:
        found = self.ledger.get_plan(plan_id)
        if not found:
            raise ServiceError("That plan no longer exists. Send /plan for a fresh one.")
        plan, status = found
        if status == "executed":
            raise ServiceError("Already recorded. Use /undo if that was a mistake.")
        rec = self.record_buys([(ln.ticker, ln.amount, None) for ln in plan.lines], note=f"plan #{plan_id}")
        self.ledger.set_plan_status(plan_id, "executed", rec.batch)
        return rec

    def skip_plan(self, plan_id: int) -> None:
        self.ledger.set_plan_status(plan_id, "skipped")

    # ── write side ─────────────────────────────────────────────────────
    def record_buys(
        self, items: list[tuple[str, float, float | None]], note: str = "", shares_mode: bool = False
    ) -> Recorded:
        """items: (ticker, dollars-or-shares, price or None for live price)."""
        warnings: list[str] = []
        tickers = [normalize_ticker(t) for t, _, _ in items]
        live = self.prices.get_prices([t for (t, (_, _, p)) in zip(tickers, items, strict=True) if p is None])
        rows, out = [], []
        for t, (_, qty, price) in zip(tickers, items, strict=True):
            if qty <= 0:
                raise ServiceError(f"{t}: amount must be positive.")
            px = price or live.get(t)
            if not px:
                raise ServiceError(f"No price for {t}. Add it: /bought {t} {qty:g} @ <price>")
            shares = qty if shares_mode else qty / px
            rows.append((t, "buy", shares, px))
            out.append((t, shares, px, shares * px))
            if t not in self.strategy.targets:
                warnings.append(f"{t} isn't in your strategy targets; tracked but never auto-bought.")
        try:
            batch = self.ledger.record(rows, note=note)
        except LedgerError as exc:
            raise ServiceError(str(exc)) from exc
        return Recorded(batch, out, warnings)

    def record_sell(self, ticker: str, shares: float, price: float | None) -> Recorded:
        t = normalize_ticker(ticker)
        px = price or self.prices.get_prices([t]).get(t)
        if not px:
            raise ServiceError(f"No price for {t}; include one: /sold {t} {shares:g} @ <price>")
        try:
            batch = self.ledger.record([(t, "sell", shares, px)], note="manual sell")
        except LedgerError as exc:
            raise ServiceError(str(exc)) from exc
        return Recorded(batch, [(t, -shares, px, -shares * px)], [])

    def undo(self) -> list[Tx]:
        return self.ledger.undo_last()

    def import_holdings(self, filename: str, content: bytes | str) -> list[tuple[str, float, float]]:
        try:
            rows = parse_file(filename, content)
        except ValueError as exc:
            raise ServiceError(str(exc)) from exc
        self.ledger.replace_with_import(rows, note=f"import {filename}")
        return rows
