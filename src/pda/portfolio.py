"""Turn ledger holdings + prices into a valued Snapshot with target drift."""

from __future__ import annotations

from pda.config import Strategy
from pda.ledger import Holding
from pda.models import Position, Snapshot


def build_snapshot(
    holdings: dict[str, Holding],
    strategy: Strategy,
    prices: dict[str, float | None],
) -> Snapshot:
    tickers = list(strategy.targets) + [t for t in holdings if t not in strategy.targets]
    positions: dict[str, Position] = {}
    missing: list[str] = []

    for t in tickers:
        h = holdings.get(t, Holding(0.0, 0.0))
        spec = strategy.spec(t)
        price = prices.get(t)
        stale = False
        if price is not None:
            value = h.shares * price
        else:
            # No live price: value at cost so totals stay sane, and say so.
            value = h.cost
            stale = h.shares > 0
            missing.append(t)
        positions[t] = Position(
            ticker=t,
            shares=h.shares,
            cost_basis=h.cost,
            price=price,
            target_pct=spec.pct if spec else 0.0,
            bucket=spec.bucket if spec else "untargeted",
            ai=spec.ai if spec else False,
            value=round(value, 2),
            price_is_stale=stale,
        )

    total_value = sum(p.value for p in positions.values())
    total_cost = sum(p.cost_basis for p in positions.values())
    for p in positions.values():
        p.actual_pct = round(p.value / total_value * 100, 2) if total_value > 0 else 0.0

    return Snapshot(
        positions=positions,
        total_value=round(total_value, 2),
        total_cost=round(total_cost, 2),
        missing_prices=missing,
    )
