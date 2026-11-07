"""Guardrails: deterministic rules applied to every proposed buy list.

Each rule *moves* money rather than just complaining, and records a
plain-English Adjustment so the user (and the LLM) can explain why.
Every rule except "never sell" is optional and configured per user.

Rules, in order:
  1. Never sell     – amounts are clamped at >= 0.
  2. Position caps  – no single stock above N% of the post-buy portfolio
                      (plus per-ticker caps, e.g. your employer's stock).
  3. Core ratio     – e.g. VOO must stay >= 3x QQQM after the buy.
  4. Cushions       – no non-theme buy may exceed the cushion tickers.
Any money a rule frees up goes to the overflow ticker.
"""

from __future__ import annotations

import math

from pda.config import Strategy
from pda.models import Adjustment, RuleCheck, Snapshot
from pda.money import money as _fmt


def headroom(ticker: str, snap: Snapshot, strategy: Strategy, post_total: float) -> float | None:
    """Money this ticker can still absorb before hitting its cap (None = uncapped).

    Rounded *down* so that rounding a buy can never push a ticker over its cap.
    """
    cap = strategy.guardrails.cap_for(strategy.spec(ticker), ticker)
    if cap is None:
        return None
    return float(max(0, math.floor(cap / 100 * post_total - snap.value_of(ticker))))


def apply_guardrails(
    buys: dict[str, float], snap: Snapshot, strategy: Strategy
) -> tuple[dict[str, float], list[Adjustment]]:
    g = strategy.guardrails
    buys = {t: float(a) for t, a in buys.items()}
    notes: list[Adjustment] = []
    overflow = 0.0
    capped: set[str] = set()

    # 1. Never sell.
    for t, a in list(buys.items()):
        if a < 0:
            notes.append(Adjustment("never_sell", f"Dropped a negative amount for {t}: the plan is buy-only."))
            buys[t] = 0.0

    post_total = snap.total_value + sum(buys.values())

    # 2. Position caps (measured against the portfolio *after* this month's buys).
    for t, a in list(buys.items()):
        if a <= 0 or t == g.overflow_ticker:
            continue
        room = headroom(t, snap, strategy, post_total)
        if room is not None and a > room + 0.5:
            cap = g.cap_for(strategy.spec(t), t)
            excess = a - room
            buys[t] = room
            capped.add(t)
            overflow += excess
            now = snap.positions[t].actual_pct if t in snap.positions else 0.0
            notes.append(Adjustment(
                "position_cap",
                f"{t} is at {now:.1f}% (cap {cap:g}%). Bought {_fmt(room)} instead of {_fmt(a)}; "
                f"{_fmt(excess)} moved to {g.overflow_ticker}.",
            ))
    if overflow > 0:
        buys[g.overflow_ticker] = buys.get(g.overflow_ticker, 0.0) + overflow

    # 3. Core ratio: (V + v + (q - q')) >= m * (Q + q')  =>  q' <= (V + v + q - m*Q) / (1 + m)
    if g.has_core_ratio:
        core, versus, m = g.core_ticker, g.core_versus, g.core_min_multiple
        q = buys.get(versus, 0.0)
        if q > 0:
            V, Q = snap.value_of(core), snap.value_of(versus)
            v = buys.get(core, 0.0)
            q_max = float(max(0, math.floor((V + v + q - m * Q) / (1 + m))))
            if q > q_max + 0.5:
                moved = q - q_max
                buys[versus] = q_max
                buys[core] = v + moved
                ratio = (V / Q) if Q else float("inf")
                notes.append(Adjustment(
                    "core_ratio",
                    f"{core} is {ratio:.1f}x {versus} (rule: at least {m:g}x). "
                    f"{_fmt(moved)} of the {versus} buy moved to {core}.",
                ))

    # 4. Cushions stay the biggest non-theme buys. A cushion held back by its own
    #    cap doesn't count; otherwise one capped cushion would starve everything else.
    cushions = [c for c in g.cushions if c in strategy.targets and c not in capped]
    floor = min((buys.get(c, 0.0) for c in cushions), default=0.0)
    if cushions and floor > 0:
        for t, a in list(buys.items()):
            spec = strategy.spec(t)
            if not spec or spec.ai or spec.bucket == "core_etf" or t in cushions or t == g.overflow_ticker:
                continue
            if a > floor + 0.5:
                excess = a - floor
                buys[t] = floor
                share = excess / len(cushions)
                for c in cushions:
                    room = headroom(c, snap, strategy, post_total)
                    room = share if room is None else max(0.0, min(share, room - buys.get(c, 0.0)))
                    buys[c] = buys.get(c, 0.0) + room
                    if share - room > 0:
                        buys[g.overflow_ticker] = buys.get(g.overflow_ticker, 0.0) + share - room
                notes.append(Adjustment(
                    "cushions",
                    f"{t} would out-buy {' and '.join(cushions)}; {_fmt(excess)} moved to them "
                    f"so the defensive cushion stays largest.",
                ))

    return {t: a for t, a in buys.items() if a > 0.004}, notes


def check_portfolio(snap: Snapshot, strategy: Strategy, sell_count: int = 0) -> list[RuleCheck]:
    """Status of every configured guardrail against the portfolio as it stands today."""
    g = strategy.guardrails
    checks: list[RuleCheck] = []

    if g.has_core_ratio:
        V, Q = snap.value_of(g.core_ticker), snap.value_of(g.core_versus)
        ratio = V / Q if Q else float("inf")
        if ratio >= g.core_min_multiple:
            checks.append(RuleCheck("Core ratio", "ok", f"{g.core_ticker} is {ratio:.1f}x {g.core_versus} (need {g.core_min_multiple:g}x)."))
        else:
            need = g.core_min_multiple * Q - V
            checks.append(RuleCheck(
                "Core ratio", "warn",
                f"{g.core_ticker} is only {ratio:.1f}x {g.core_versus} (need {g.core_min_multiple:g}x). "
                f"{g.core_versus} buys go to {g.core_ticker} until about {_fmt(need)} more {g.core_ticker} is added.",
            ))

    if g.max_single_stock_pct is not None or g.per_ticker_caps:
        over = []
        for p in snap.positions.values():
            cap = g.cap_for(strategy.spec(p.ticker), p.ticker)
            if cap is not None and p.actual_pct > cap + 0.05:
                over.append(f"{p.ticker} {p.actual_pct:.1f}% (cap {cap:g}%)")
        if over:
            checks.append(RuleCheck(
                "Position caps", "warn",
                "Over cap: " + ", ".join(over) + ". No new buys there. Don't sell: new money will shrink them over time.",
            ))
        else:
            parts = []
            if g.max_single_stock_pct is not None:
                parts.append(f"no stock above {g.max_single_stock_pct:g}%")
            parts += [f"{t} ≤ {c:g}%" for t, c in g.per_ticker_caps.items()]
            checks.append(RuleCheck("Position caps", "ok", "All within caps: " + ", ".join(parts) + "."))

    if g.cushions:
        cushion_pct = sum(snap.positions[c].actual_pct for c in g.cushions if c in snap.positions)
        cushion_target = sum(strategy.targets[c].pct for c in g.cushions if c in strategy.targets)
        status = "ok" if cushion_pct >= cushion_target * 0.75 else "warn"
        detail = f"{' + '.join(g.cushions)} = {cushion_pct:.1f}% of portfolio (target {cushion_target:g}%)."
        if strategy.has_theme:
            detail += f" Theme-heavy positions = {snap.ai_pct():.1f}%."
        checks.append(RuleCheck("Cushions", status, detail))

    if sell_count == 0:
        checks.append(RuleCheck("Never sell", "ok", "0 sells recorded. Keep it that way in a drop."))
    else:
        checks.append(RuleCheck("Never sell", "warn", f"{sell_count} sell(s) recorded. The plan is buy-only."))

    drift = sorted(
        (p for p in snap.positions.values() if p.target_pct > 0),
        key=lambda p: abs(p.gap_pct), reverse=True,
    )[:3]
    if drift and snap.total_value > 0:
        checks.append(RuleCheck(
            "New-money rebalancing", "ok",
            "Biggest drifts (closed with new buys only): "
            + ", ".join(f"{p.ticker} {p.actual_pct:.1f}% vs {p.target_pct:g}%" for p in drift),
        ))
    return checks
