import pytest

from pda.config import DEMO_STRATEGY, load_strategy
from pda.ledger import Ledger
from pda.prices import StaticPrices
from pda.service import Service

HOLDINGS = [  # same made-up portfolio as examples/holdings.example.yaml: QQQ-heavy, NVDA over cap
    ("VTI", 40.0, 300.0), ("QQQ", 16.0, 520.0), ("VXUS", 60.0, 70.0), ("BND", 40.0, 72.0),
    ("GLD", 6.0, 250.0), ("NVDA", 25.0, 120.0), ("MSFT", 5.0, 410.0), ("AAPL", 6.0, 220.0),
    ("AMZN", 4.0, 190.0), ("COST", 1.0, 900.0), ("TSLA", 2.0, 250.0),
]


@pytest.fixture
def strategy():
    return load_strategy(DEMO_STRATEGY)


@pytest.fixture
def prices():
    return StaticPrices.from_yaml()


@pytest.fixture
def ledger():
    return Ledger(":memory:")


@pytest.fixture
def service(strategy, ledger, prices):
    svc = Service(strategy, ledger, prices)
    ledger.replace_with_import(HOLDINGS)
    return svc


@pytest.fixture
def empty_service(strategy, ledger, prices):
    return Service(strategy, ledger, prices)
