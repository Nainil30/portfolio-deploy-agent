import pytest

from pda.engine import extra_plan, monthly_plan
from pda.ledger import Holding
from pda.portfolio import build_snapshot


def snap_from(strategy, prices, holdings):
    h = {t: Holding(s, s * c) for t, s, c in holdings}
    return build_snapshot(h, strategy, prices.get_prices(sorted(set(strategy.targets) | set(h))))


def amounts(plan):
    return {ln.ticker: ln.amount for ln in plan.lines}


# ── monthly plan ────────────────────────────────────────────────────────
def test_monthly_total_is_exact_and_buy_only(service):
    plan, _ = service.plan()
    assert plan.total == 1500
    assert all(ln.amount > 0 for ln in plan.lines)


def test_balanced_portfolio_gets_written_split(strategy, prices):
    # Holdings exactly at target -> written split, slot goes to a candidate.
    total = 100_000
    holdings = [(t, total * s.pct / 100 / prices.prices[t], prices.prices[t]) for t, s in strategy.targets.items()]
    snap = snap_from(strategy, prices, holdings)
    a = amounts(monthly_plan(snap, strategy))
    for t in ("XLV", "BND", "VXUS", "GLD", "QQQ"):
        assert a[t] == strategy.split[t]
    # BRK.B sits exactly at its 6% cap, so only the headroom is bought; the rest goes to VTI.
    assert 0 < a["BRK.B"] < strategy.split["BRK.B"]
    slot = {t: v for t, v in a.items() if t in strategy.slot_candidates}
    assert sum(slot.values()) == 200


def test_core_ratio_redirects_qqq_to_vti(service):
    plan, snap = service.plan()
    a = amounts(plan)
    assert "QQQ" not in a  # VTI is ~1.4x QQQ, so the whole $75 moves
    assert a["VTI"] >= 625
    assert any(n.rule == "core_ratio" for n in plan.notes)


def test_core_ratio_partial_when_close(strategy, prices):
    # VTI slightly under 3x QQQ after the buy -> only part of QQQ's $75 moves.
    vti, qqq = prices.prices["VTI"], prices.prices["QQQ"]
    snap = snap_from(strategy, prices, [("VTI", 30000 / vti, vti), ("QQQ", 10150 / qqq, qqq)])
    a = amounts(monthly_plan(snap, strategy))
    V, Q = 30000 + a.get("VTI", 0), 10150 + a.get("QQQ", 0)
    assert V >= 3 * Q - 1
    assert 0 < a.get("QQQ", 0) < 75


def test_slot_goes_to_furthest_below_target(service):
    plan, snap = service.plan()
    a = amounts(plan)
    cands = [snap.positions[t] for t in service.strategy.slot_candidates]
    best = max(cands, key=lambda p: p.gap_pct)
    assert a.get(best.ticker, 0) >= 200


def test_slot_skips_capped_stocks(service):
    plan, snap = service.plan()
    a = amounts(plan)
    assert snap.positions["NVDA"].actual_pct > 5
    assert "NVDA" not in a and "MSFT" not in a


def test_no_stock_exceeds_cap_after_buys(service):
    for amount in (1500, 6000, 20000):
        plan, snap = service.plan(amount)
        post = snap.total_value + plan.total
        for ln in plan.lines:
            cap = service.strategy.guardrails.cap_for(service.strategy.spec(ln.ticker), ln.ticker)
            if cap is not None:
                assert snap.value_of(ln.ticker) + ln.amount <= cap / 100 * post + 1


def test_per_ticker_cap_at_three_percent(strategy, prices):
    # AAPL at ~2.3% with a 3% target and cap: a big cash injection may top it up, never past 3%.
    snap = snap_from(strategy, prices, [("VTI", 100, 371), ("AAPL", 2.5, 356)])
    plan = extra_plan(snap, strategy, 2000)
    post = snap.total_value + 2000
    assert snap.value_of("AAPL") + amounts(plan).get("AAPL", 0) <= 0.03 * post + 1


def test_scaled_plan(service):
    plan, _ = service.plan(3000)
    assert plan.total == 3000
    assert amounts(plan)["XLV"] == 300  # 150 * 2


def test_capped_ticker_never_bought_when_over_cap(strategy, prices):
    snap = snap_from(strategy, prices, [("VTI", 100, 371), ("AAPL", 4, 356)])  # AAPL ~3.7%
    assert "AAPL" not in amounts(extra_plan(snap, strategy, 2000))


def test_cushions_remain_biggest_non_ai_buys(service):
    plan, _ = service.plan()
    a = amounts(plan)
    s = service.strategy
    cushion_floor = min(a.get(c, 0) for c in s.guardrails.cushions)
    for t, amt in a.items():
        spec = s.spec(t)
        if spec and not spec.ai and spec.bucket != "core_etf" and t not in s.guardrails.cushions:
            assert amt <= cushion_floor


def test_missing_price_candidate_is_skipped(strategy, prices):
    prices.prices.pop("COST")
    snap = snap_from(strategy, prices, [("VTI", 10, 371)])
    plan = monthly_plan(snap, strategy)
    assert "COST" not in amounts(plan)
    assert any("COST skipped" in n.message for n in plan.notes)
    assert plan.total == 1500


def test_empty_portfolio_still_plans(empty_service):
    plan, _ = empty_service.plan()
    assert plan.total == 1500


def test_zero_amount_rejected(service):
    with pytest.raises(ValueError):
        monthly_plan(service.snapshot(), service.strategy, -5)
    with pytest.raises(ValueError):
        extra_plan(service.snapshot(), service.strategy, 0)


# ── extra cash ──────────────────────────────────────────────────────────
def test_extra_fills_biggest_gaps(service):
    plan, snap = service.extra(5000)
    a = amounts(plan)
    assert plan.total == 5000
    assert a["XLV"] > 0 and a["BRK.B"] > 0  # both at 0% vs 6% / 6%
    for t in ("QQQ", "NVDA", "MSFT", "AAPL"):  # overweight -> nothing
        assert t not in a


def test_extra_never_negative(service):
    for cash in (100, 1000, 50_000):
        plan, _ = service.extra(cash)
        assert all(ln.amount > 0 for ln in plan.lines)
        assert plan.total == round(cash)
