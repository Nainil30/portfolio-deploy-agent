import copy

import pytest
import yaml

from pda.config import DEMO_STRATEGY, ConfigError, normalize_ticker, parse_strategy


@pytest.fixture
def raw():
    with open(DEMO_STRATEGY, encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_shipped_strategy_is_valid(strategy):
    assert abs(sum(t.pct for t in strategy.targets.values()) - 100) < 1e-9
    assert sum(strategy.split.values()) + strategy.slot_amount == strategy.monthly_amount == 1500


def test_bucket_totals_match_written_plan(strategy):
    by_bucket = {}
    for t in strategy.targets.values():
        by_bucket[t.bucket] = by_bucket.get(t.bucket, 0) + t.pct
    assert by_bucket == pytest.approx({"core_etf": 45, "etf": 18, "bond": 10, "gold": 5, "stock": 22})


def test_per_ticker_caps_override_single_stock_cap(strategy):
    g = strategy.guardrails
    assert g.cap_for(strategy.spec("AAPL"), "AAPL") == 3
    assert g.cap_for(strategy.spec("BRK.B"), "BRK.B") == 6
    assert g.cap_for(strategy.spec("NVDA"), "NVDA") == 5


def test_vti_target_is_3x_qqq(strategy):
    assert strategy.targets["VTI"].pct >= 3 * strategy.targets["QQQ"].pct


def test_targets_must_sum_to_100(raw):
    bad = copy.deepcopy(raw)
    bad["targets"]["VTI"]["pct"] = 36
    with pytest.raises(ConfigError, match="add up to 101"):
        parse_strategy(bad)


def test_split_must_match_monthly_amount(raw):
    bad = copy.deepcopy(raw)
    bad["monthly"]["split"]["VTI"] = 600
    with pytest.raises(ConfigError, match="monthly.amount"):
        parse_strategy(bad)


def test_cushions_must_be_biggest_non_ai_buys(raw):
    bad = copy.deepcopy(raw)
    bad["monthly"]["split"]["GLD"] = 200
    bad["monthly"]["split"]["VTI"] = 425
    with pytest.raises(ConfigError, match="bigger non-theme buy"):
        parse_strategy(bad)


def test_target_above_cap_rejected(raw):
    bad = copy.deepcopy(raw)
    bad["targets"]["NVDA"]["pct"] = 6
    bad["targets"]["MSFT"]["pct"] = 2
    with pytest.raises(ConfigError, match="above its cap"):
        parse_strategy(bad)


@pytest.mark.parametrize("raw_t", ["brk.b", "BRK-B", "brk/b", "BRKB", "$BRK.B"])
def test_normalize_berkshire(raw_t):
    assert normalize_ticker(raw_t) == "BRK.B"
