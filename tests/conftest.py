import pytest

from pda.config import load_strategy
from pda.ledger import Ledger
from pda.prices import StaticPrices
from pda.service import Service

HOLDINGS = [  # roughly the real starting portfolio: QQQM-heavy, NVDA over cap
    ("VOO", 18.0, 560.0), ("QQQM", 34.0, 225.0), ("SCHD", 120.0, 27.0), ("SMH", 2.3, 340.0),
    ("VXUS", 13.0, 77.0), ("IAUM", 46.0, 42.0), ("NVDA", 19.0, 134.0), ("GOOGL", 8.0, 316.0),
    ("DELL", 6.4, 264.0), ("PLTR", 8.9, 125.0), ("AMZN", 3.7, 212.0), ("MSFT", 1.5, 401.0),
    ("TSLA", 1.2, 393.0), ("AMD", 0.6, 313.0), ("LLY", 0.5, 822.0), ("INTC", 2.8, 71.0),
    ("ORCL", 0.43, 234.0),
]


@pytest.fixture
def strategy():
    return load_strategy()


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
