"""The plan engine: deterministic, explainable buy lists.

  monthly_plan  – mode "fixed": the written split + a "stock slot" that goes
                  to the candidate furthest below target, then guardrails.
                  mode "auto":  the whole amount fills the biggest gaps vs
                  target (rebalance with new money), then guardrails.
  extra_plan    – one-off cash (bonus, tax refund): always gap-fill.

No LLM is involved here. Money decisions are pure functions you can unit-test.
"""

from __future__ import annotations

from pda.config import Strategy
from pda.guardrails import apply_guardrails, headroom
from pda.models import Adjustment, BuyLine, Plan, Snapshot
from pda.money import money


def pick_slot(
    snap: Snapshot, strategy: Strategy, slot: float, post_total: float, planned: dict[str, float]
) -> tuple[dict[str, float], dict[str, str], list[Adjustment]]:
    """Give the stock slot to the candidate(s) furthest below target, respecting caps."""
    alloc: dict[str, float] = {}
    reasons: dict[str, str] = {}
    notes: list[Adjustment] = []
    if slot <= 0:
        return alloc, reasons, notes

    priced = []
    for t in strategy.slot_candidates:
        p = snap.positions.get(t)
        if p is None or p.price is None:
            notes.append(Adjustment("stock_slot", f"{t} skipped: no live price (check the ticker in strategy.yaml)."))
            continue
        priced.append(p)

    ranked = sorted(priced, key=lambda p: p.gap_pct, reverse=True)
    remaining = slot
    for p in ranked:
        room = headroom(p.ticker, snap, strategy, post_total)
        room = remaining if room is None else room - planned.get(p.ticker, 0.0)
        if room < strategy.min_buy:
            notes.append(Adjustment("stock_slot", f"{p.ticker} skipped: at its {p.actual_pct:.1f}% cap."))
            continue
        take = min(remaining, room)
        first = not alloc
        alloc[p.ticker] = alloc.get(p.ticker, 0.0) + take
        where = "below" if p.gap_pct > 0 else "above"
        reasons[p.ticker] = (
            f"Stock slot: {p.actual_pct:.1f}% vs {p.target_pct:g}% target "
            f"({abs(p.gap_pct):.1f} pts {where}, furthest below of {len(ranked)} candidates)"
            if first else
            f"Stock slot (remainder): {p.actual_pct:.1f}% vs {p.target_pct:g}% target"
        )
        remaining -= take
        if remaining < 0.5:
            break

    if remaining >= 0.5:
        of = strategy.guardrails.overflow_ticker
        alloc[of] = alloc.get(of, 0.0) + remaining
        notes.append(Adjustment("stock_slot", f"All slot candidates are at their caps; {money(remaining)} goes to {of}."))
    return alloc, reasons, notes


def gap_fill(
    snap: Snapshot, strategy: Strategy, cash: float
) -> tuple[dict[str, float], dict[str, str], list[Adjustment]]:
    """Split cash across tickers in proportion to how far each is below target
    *after* the cash is added (respecting caps)."""
    post_total = snap.total_value + cash
    shortfall: dict[str, float] = {}
    reasons: dict[str, str] = {}
    notes: list[Adjustment] = []
    for t, spec in strategy.targets.items():
        p = snap.positions[t]
        if p.price is None:
            notes.append(Adjustment("price", f"{t} skipped: no live price."))
            continue
        gap = spec.pct / 100 * post_total - p.value
        room = headroom(t, snap, strategy, post_total)
        if room is not None:
            gap = min(gap, room)
        if gap > 0:
            shortfall[t] = gap
            reasons[t] = f"Gap fill: {p.actual_pct:.1f}% vs {spec.pct:g}% target"

    total_short = sum(shortfall.values())
    if total_short <= 0:
        of = strategy.guardrails.overflow_ticker
        reasons[of] = "Everything is at/above target; core holding"
        return {of: cash}, reasons, notes
    if total_short >= cash:
        return {t: cash * g / total_short for t, g in shortfall.items()}, reasons, notes

    buys = dict(shortfall)
    leftover = cash - total_short
    priced = {t: s for t, s in strategy.targets.items() if snap.positions[t].price is not None}
    weight = sum(s.pct for s in priced.values()) or 1.0
    for t, spec in priced.items():
        buys[t] = buys.get(t, 0.0) + leftover * spec.pct / weight
        reasons.setdefault(t, "Pro-rata to target")
    notes.append(Adjustment("gap_fill", f"All gaps closed; remaining {money(leftover)} spread by target weight."))
    return buys, reasons, notes


def _finalize(
    kind: str,
    amount: float,
    before: dict[str, float],
    after: dict[str, float],
    reasons: dict[str, str],
    notes: list[Adjustment],
    snap: Snapshot,
    strategy: Strategy,
) -> Plan:
    of = strategy.guardrails.overflow_ticker
    after = dict(after)

    # Fold dust into the overflow ticker: tiny orders are noise.
    for t, a in list(after.items()):
        if t != of and 0 < a < strategy.min_buy:
            after[of] = after.get(of, 0.0) + a
            del after[t]
            notes.append(Adjustment("min_buy", f"{t} {money(a)} is below the {money(strategy.min_buy)} minimum; added to {of}."))

    # Whole units, and the total must equal what you're investing.
    rounded = {t: float(round(a)) for t, a in after.items() if round(a) > 0}
    residual = round(amount) - sum(rounded.values())
    if residual:
        rounded[of] = rounded.get(of, 0.0) + residual

    lines = []
    for t, a in sorted(rounded.items(), key=lambda kv: -kv[1]):
        reason = reasons.get(t, "Redirected by guardrails")
        b = before.get(t, 0.0)
        if t in before and a > b + 0.5:
            reason += f" (+{money(a - b)} redirected)"
        elif a < b - 0.5:
            reason += f" (trimmed from {money(b)})"
        p = snap.positions.get(t)
        lines.append(BuyLine(t, a, reason, p.price if p else None))
    return Plan(kind=kind, amount=float(round(amount)), lines=lines, notes=notes)


def monthly_plan(snap: Snapshot, strategy: Strategy, amount: float | None = None) -> Plan:
    amount = float(amount if amount is not None else strategy.monthly_amount)
    if amount <= 0:
        raise ValueError("Amount must be positive")
    notes: list[Adjustment] = []

    if strategy.mode == "auto":
        buys, reasons, notes = gap_fill(snap, strategy, amount)
    else:
        scale = amount / strategy.split_base
        post_total = snap.total_value + amount
        buys = {t: a * scale for t, a in strategy.split.items()}
        reasons = {t: "Monthly split" for t in buys}
        if abs(scale - 1) > 1e-9:
            notes.append(Adjustment("scale", f"Split scaled x{scale:.2f} for {money(amount)}."))
        slot_alloc, slot_reasons, slot_notes = pick_slot(
            snap, strategy, strategy.slot_amount * scale, post_total, buys
        )
        for t, a in slot_alloc.items():
            buys[t] = buys.get(t, 0.0) + a
            if t in slot_reasons:
                reasons[t] = slot_reasons[t] if t not in reasons else reasons[t] + " + " + slot_reasons[t]
        notes += slot_notes

    after, g_notes = apply_guardrails(buys, snap, strategy)
    return _finalize("monthly", amount, buys, after, reasons, notes + g_notes, snap, strategy)


def extra_plan(snap: Snapshot, strategy: Strategy, cash: float) -> Plan:
    """Deploy one-off cash into the largest shortfalls vs target (new-money rebalance)."""
    if cash <= 0:
        raise ValueError("Amount must be positive")
    buys, reasons, notes = gap_fill(snap, strategy, cash)
    after, g_notes = apply_guardrails(buys, snap, strategy)
    return _finalize("extra", cash, buys, after, reasons, notes + g_notes, snap, strategy)
