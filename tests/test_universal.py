"""Anyone's plan: presets, auto mode, wizard, settings, international tickers, currency."""

import asyncio
from pathlib import Path

import pytest
import yaml

from pda import formatting as fmt
from pda.config import EXAMPLES_DIR, ConfigError, load_strategy, normalize_ticker, parse_strategy
from pda.engine import monthly_plan
from pda.importers import parse_csv
from pda.ledger import Holding, Ledger
from pda.llm import system_prompt
from pda.money import set_currency
from pda.onboarding import demo_service, parse_target_line, run_doctor, run_wizard, scale_split
from pda.portfolio import build_snapshot
from pda.prices import StaticPrices, YahooPrices
from pda.service import Service, ServiceError

PRESETS = sorted(p for p in EXAMPLES_DIR.glob("*.yaml") if "holdings" not in p.name)


@pytest.fixture(autouse=True)
def _reset_currency():
    yield
    set_currency("$")


@pytest.mark.parametrize("path", PRESETS, ids=lambda p: p.stem)
def test_every_preset_is_valid(path):
    s = load_strategy(path)
    assert abs(sum(t.pct for t in s.targets.values()) - 100) < 1e-9


def minimal(**over):
    raw = {"goal": {"target_value": 50000}, "monthly": {"amount": 300},
           "targets": {"VTI": 70, "VXUS": 30}}
    raw.update(over)
    return raw


def test_minimal_plan_defaults_to_auto_mode():
    s = parse_strategy(minimal())
    assert s.mode == "auto"
    assert s.guardrails.overflow_ticker == "VTI"   # largest target
    assert not s.guardrails.has_core_ratio and s.guardrails.cushions == ()


def test_auto_mode_rejects_split():
    with pytest.raises(ConfigError, match="mode is 'auto'"):
        parse_strategy(minimal(monthly={"amount": 300, "mode": "auto", "split": {"VTI": 300}}))


def test_unknown_bucket_rejected():
    with pytest.raises(ConfigError, match="bucket"):
        parse_strategy(minimal(targets={"VTI": {"pct": 100, "bucket": "magic"}}))


def test_auto_mode_fills_biggest_gap():
    s = parse_strategy(minimal())
    prices = StaticPrices({"VTI": 300, "VXUS": 60})
    snap = build_snapshot({"VTI": Holding(10, 3000)}, s, prices.get_prices(["VTI", "VXUS"]))  # VXUS at 0%
    plan = monthly_plan(snap, s)
    amounts = {ln.ticker: ln.amount for ln in plan.lines}
    assert plan.total == 300
    assert amounts == {"VXUS": 300}  # all new money to the underweight fund


def test_auto_mode_empty_portfolio_follows_targets():
    s = parse_strategy(minimal())
    snap = build_snapshot({}, s, {"VTI": 300.0, "VXUS": 60.0})
    amounts = {ln.ticker: ln.amount for ln in monthly_plan(snap, s).lines}
    assert amounts == {"VTI": 210, "VXUS": 90}


@pytest.mark.parametrize("raw,expect", [
    ("reliance.ns", "RELIANCE.NS"), ("BTC-USD", "BTC-USD"), ("shop.to", "SHOP.TO"),
    ("vod.l", "VOD.L"), ("BRK-B", "BRK.B"), ("$aapl", "AAPL"),
])
def test_international_tickers_normalize(raw, expect):
    assert normalize_ticker(raw) == expect


@pytest.mark.parametrize("ticker,symbol", [
    ("BRK.B", "BRK-B"), ("RELIANCE.NS", "RELIANCE.NS"), ("BTC-USD", "BTC-USD"), ("VOO", "VOO"),
])
def test_yahoo_symbols(ticker, symbol):
    assert YahooPrices()._symbol(ticker) == symbol


def test_currency_flows_into_messages():
    s = load_strategy(EXAMPLES_DIR / "india_index.yaml")
    svc = Service(s, Ledger(":memory:"), StaticPrices({t: 100 for t in s.targets}))
    plan, snap = svc.plan()
    html = fmt.fmt_plan(plan, snap)
    assert "₹25,000" in html and "$" not in html.replace("$", "", 0).split("Personal")[0]


# ── settings overrides ─────────────────────────────────────────────────
def test_set_monthly_scales_fixed_split(service):
    service.set_setting("monthly", "3000")
    plan, _ = service.plan()
    assert plan.total == 3000
    assert {ln.ticker: ln.amount for ln in plan.lines}["VHT"] == 375


def test_settings_persist_and_reset(service, strategy, prices):
    service.set_setting("goal", "250k")
    service.set_setting("day", "20")
    service.set_setting("return", "6")
    again = Service(strategy, service.ledger, prices)  # restart
    assert again.strategy.goal_value == 250_000
    assert again.strategy.reminder_day == 20
    assert again.strategy.expected_return == pytest.approx(0.06)
    again.reset_settings()
    assert again.strategy.goal_value == strategy.goal_value


@pytest.mark.parametrize("key,value", [("day", "31"), ("monthly", "-5"), ("color", "blue"), ("goal", "lots")])
def test_bad_settings_rejected(service, key, value):
    with pytest.raises(ServiceError):
        service.set_setting(key, value)


# ── wizard ─────────────────────────────────────────────────────────────
def scripted(answers):
    it = iter(answers)
    return lambda prompt: next(it)


def test_wizard_custom_plan(tmp_path):
    path = tmp_path / "strategy.yaml"
    answers = ["Retirement", "€", "800", "300k", "6", "10", "Europe/Berlin",
               "5",                       # custom
               "VWCE.DE 70", "bad line", "AGGH.AS 20 bond", "SAP.DE 10 stock", "",
               "8"]                       # stock cap
    run_wizard(ask=scripted(answers), out=lambda *_: None, path=path, force=True)
    s = load_strategy(path)
    assert s.name == "Retirement" and s.currency == "€"
    assert s.monthly_amount == 800 and s.goal_value == 300_000 and s.reminder_day == 10
    assert s.targets["VWCE.DE"].bucket == "core_etf"
    assert s.guardrails.max_single_stock_pct == 10  # raised to fit SAP.DE 10%
    assert s.mode == "auto"


def test_wizard_scales_targets_to_100(tmp_path):
    path = tmp_path / "s.yaml"
    answers = ["", "", "500", "100000", "", "", "", "5", "VTI 3", "BND 1", "", ""]
    run_wizard(ask=scripted(answers), out=lambda *_: None, path=path, force=True)
    s = load_strategy(path)
    assert s.targets["VTI"].pct == 75 and s.targets["BND"].pct == 25


def test_wizard_preset_rescales_fixed_split(tmp_path):
    path = tmp_path / "s.yaml"
    run_wizard(path=path, preset="core_plus_stock_slot", force=True, out=lambda *_: None,
               defaults={"name": None, "currency": None, "monthly": 3000, "goal": None,
                         "return": None, "day": None, "timezone": None})
    s = load_strategy(path)
    assert s.monthly_amount == 3000 and s.split_base == 3000
    assert s.split["VOO"] == 975 and s.slot_amount == 600


def test_wizard_keeps_existing_file(tmp_path):
    path = tmp_path / "s.yaml"
    path.write_text("keep me")
    run_wizard(ask=scripted(["n"]), out=lambda *_: None, path=path)
    assert path.read_text() == "keep me"


def test_scale_split_exact_total():
    m = {"split": {"A": 650, "B": 250, "C": 100}, "stock_slot": {"amount": 400}}
    scale_split(m, 1234)
    assert sum(m["split"].values()) + m["stock_slot"]["amount"] == 1234


def test_parse_target_line():
    assert parse_target_line("gld 10% gold") == ("GLD", 10.0, "gold")
    with pytest.raises(ValueError):
        parse_target_line("VTI")


# ── demo / doctor / importer / llm prompt ──────────────────────────────
def test_demo_runs_without_any_setup(capsys):
    from pda.__main__ import demo

    assert demo(demo_service(), 5000) == 0
    text = capsys.readouterr().out
    assert "Monthly buy list" in text and "Guardrails" in text and "Stress test" in text


def test_doctor_offline_reports_missing_plan(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    lines = []
    code = run_doctor(tmp_path / "nope.yaml", tmp_path / "db.sqlite", check_network=False, out=lines.append)
    assert code == 1 and any("pda init" in ln for ln in lines)


def test_doctor_offline_ok_on_preset(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    code = run_doctor(EXAMPLES_DIR / "three_fund.yaml", tmp_path / "db.sqlite", check_network=False, out=lambda *_: None)
    assert code == 0


@pytest.mark.parametrize("csv_text", [
    "ticker,shares,avg_cost\nVTI,10,250\nBND,5,70\n",                                      # generic
    "Symbol,Description,Quantity,Price,Cost Basis\nVTI,TOTAL MKT,10,300,2500\nBND,BOND,5,72,350\n",  # Schwab-ish
    "Instrument,Qty.,Avg. cost,LTP\nVTI,10,250,300\nBND,5,70,72\n",                       # Zerodha-ish
])
def test_generic_broker_csvs(csv_text):
    rows = {t: (q, c) for t, q, c in parse_csv(csv_text)}
    assert rows["VTI"] == (10, 250) and rows["BND"] == (5, 70)


def test_system_prompt_describes_users_own_plan():
    s = load_strategy(EXAMPLES_DIR / "dividend_income.yaml")
    prompt = system_prompt(s)
    assert "Dividend income" in prompt and "$1,000/month" in prompt and "SCHD and BND" in prompt
    assert "VOO" not in prompt


def test_bot_set_command(service):
    from pda.bot import Bot
    from tests.test_bot_handlers import ctx, make_update

    b = Bot(service, "1:x", chat_id=42)
    sent = []

    async def capture(update, html, markup=None):
        sent.append(html)

    b.send = capture
    upd, _ = make_update()
    asyncio.run(b.cmd_set(upd, ctx(["monthly", "2500"])))
    assert "Saved" in sent[-1] and "$2,500" in sent[-1]
    asyncio.run(b.cmd_settings(upd, ctx()))
    assert "Changed via /set" in sent[-1]


def test_example_holdings_file_imports():
    from pda.config import DEMO_HOLDINGS
    from pda.importers import parse_file

    rows = parse_file(DEMO_HOLDINGS.name, Path(DEMO_HOLDINGS).read_text(encoding="utf-8"))
    assert len(rows) >= 10
    assert yaml.safe_load(Path(DEMO_HOLDINGS).read_text(encoding="utf-8"))["holdings"]
