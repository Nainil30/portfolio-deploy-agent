import pytest

from pda.ledger import LedgerError
from pda.service import ServiceError


def test_import_then_holdings(service):
    h = service.ledger.holdings()
    assert h["VOO"].shares == 18.0
    assert h["VOO"].cost == pytest.approx(18 * 560)


def test_execute_plan_updates_holdings_and_blocks_double_record(service):
    plan, _ = service.plan()
    before = service.ledger.holdings()["VOO"].shares
    rec = service.execute_plan(plan.id)
    assert rec.rows
    assert service.ledger.holdings()["VOO"].shares > before
    assert service.month_done()
    with pytest.raises(ServiceError, match="Already recorded"):
        service.execute_plan(plan.id)


def test_undo_reverts_plan_execution(service):
    plan, _ = service.plan()
    service.execute_plan(plan.id)
    service.undo()
    assert not service.month_done()
    assert service.ledger.holdings()["VOO"].shares == 18.0


def test_undo_import_restores_previous_holdings(service):
    service.import_holdings("h.yaml", "holdings:\n  - {ticker: VOO, shares: 1, avg_cost: 600}\n")
    assert set(service.ledger.holdings()) == {"VOO"}
    service.undo()
    assert "NVDA" in service.ledger.holdings()


def test_record_buy_dollars_and_shares(service):
    service.record_buys([("brk-b", 571, None)])
    assert service.ledger.holdings()["BRK.B"].shares == pytest.approx(1.0)
    service.record_buys([("VHT", 2, 300.0)], shares_mode=True)
    assert service.ledger.holdings()["VHT"].cost == pytest.approx(600)


def test_sell_reduces_at_average_cost(service):
    service.record_sell("VOO", 9, 700)
    h = service.ledger.holdings()["VOO"]
    assert h.shares == 9
    assert h.cost == pytest.approx(9 * 560)
    assert service.ledger.sell_count() == 1


def test_cannot_oversell(service):
    with pytest.raises(ServiceError, match="Cannot sell"):
        service.record_sell("VOO", 100, 700)


def test_ledger_rejects_nonpositive(ledger):
    with pytest.raises(LedgerError):
        ledger.record([("VOO", "buy", 0, 500)])


def test_unknown_ticker_warns(service):
    rec = service.record_buys([("COST", 100, 900.0)])
    assert rec.warnings


def test_drawdown_alert_fires_once_per_level(service):
    from datetime import date

    snap = service.snapshot()
    # Fake a much better past day: gain was $30k higher.
    service.ledger.save_snapshot(date(2026, 1, 2), snap.total_cost + snap.gain + 30_000, snap.total_cost)
    hit = service.new_drawdown_alert(snap)
    assert hit is not None
    assert service.new_drawdown_alert(snap) is None  # not repeated


def test_guardrail_report_flags_real_issues(service):
    checks = {c.name: c for c in service.guardrails()}
    assert checks["Core ratio"].status == "warn"
    assert checks["Position caps"].status == "warn" and "NVDA" in checks["Position caps"].detail
    assert checks["Never sell"].status == "ok"
