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
    assert sum(strategy.split.values()) + strategy.slot_amount == strategy.monthly_amount == 2000


def test_bucket_totals_match_written_plan(strategy):
    by_bucket = {}
    for t in strategy.targets.values():
        by_bucket[t.bucket] = by_bucket.get(t.bucket, 0) + t.pct
    assert by_bucket == pytest.approx({"core_etf": 40, "etf": 20, "gold": 8, "stock": 32})


def test_tesla_plus_spacex_is_five_percent(strategy):
    assert strategy.targets["TSLA"].pct + strategy.targets["SPCX"].pct == 5


def test_voo_target_is_3x_qqqm(strategy):
    assert strategy.targets["VOO"].pct >= 3 * strategy.targets["QQQM"].pct


def test_targets_must_sum_to_100(raw):
    bad = copy.deepcopy(raw)
    bad["targets"]["VOO"]["pct"] = 31
    with pytest.raises(ConfigError, match="add up to 101"):
        parse_strategy(bad)


def test_split_must_match_monthly_amount(raw):
    bad = copy.deepcopy(raw)
    bad["monthly"]["split"]["VOO"] = 700
    with pytest.raises(ConfigError, match="monthly.amount"):
        parse_strategy(bad)


def test_cushions_must_be_biggest_non_ai_buys(raw):
    bad = copy.deepcopy(raw)
    bad["monthly"]["split"]["IAUM"] = 300
    bad["monthly"]["split"]["VOO"] = 550
    with pytest.raises(ConfigError, match="bigger non-theme buy"):
        parse_strategy(bad)


def test_target_above_cap_rejected(raw):
    bad = copy.deepcopy(raw)
    bad["targets"]["NVDA"]["pct"] = 6
    bad["targets"]["GOOGL"]["pct"] = 3
    with pytest.raises(ConfigError, match="above its cap"):
        parse_strategy(bad)


@pytest.mark.parametrize("raw_t", ["brk.b", "BRK-B", "brk/b", "BRKB", "$BRK.B"])
def test_normalize_berkshire(raw_t):
    assert normalize_ticker(raw_t) == "BRK.B"
