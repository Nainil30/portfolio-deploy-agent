import pytest

from pda import intents
from pda.importers import ImportErrorBadFile, parse_csv
from pda.insights import months_to_goal


@pytest.mark.parametrize(
    "text,ticker,qty,shares,price",
    [
        ("bought 400 of nvda", "NVDA", 400, False, None),
        ("I bought $650 VOO", "VOO", 650, False, None),
        ("bought 2 shares of brk.b at 570", "BRK.B", 2, True, 570),
        ("buy VHT 250", "VHT", 250, False, None),
        ("bought 1.5k in voo", "VOO", 1500, False, None),
        ("bought 3 sh nvda @ 181.5", "NVDA", 3, True, 181.5),
    ],
)
def test_parse_buys(text, ticker, qty, shares, price):
    i = intents.parse(text)
    assert i.name == "buy"
    assert i.args == {"ticker": ticker, "qty": qty, "shares": shares, "price": price}


@pytest.mark.parametrize(
    "text,name",
    [
        ("how am I doing?", "portfolio"),
        ("what should I buy this month", "plan"),
        ("should I sell everything??", "sell"),
        ("how long until I hit 155k", "goal"),
        ("show guardrails", "guardrails"),
        ("📋 Plan", "plan"),
        ("what happens in a crash", "stress"),
    ],
)
def test_parse_keywords(text, name):
    assert intents.parse(text).name == name


def test_parse_extra_cash():
    i = intents.parse("I got a 5k bonus")
    assert i.name == "extra" and i.args["amount"] == 5000


def test_parse_plan_amount():
    assert intents.parse("plan 3000").args["amount"] == 3000


def test_unknown_returns_none():
    assert intents.parse("tell me a joke") is None


FIDELITY_CSV = """﻿Account Number,Account Name,Symbol,Description,Quantity,Last Price,Current Value,Cost Basis Total,Average Cost Basis,Type
Z123,Individual,SPAXX**,HELD IN MONEY MARKET,,,$512.20,,,Cash
Z123,Individual,VOO,VANGUARD S&P 500 ETF,18.261,$679.70,"$12,412.00","$10,196.57",$558.38,Cash
Z123,Individual,BRK/B,BERKSHIRE HATHAWAY INC CL B,1.5,$570.00,$855.00,$800.00,$533.33,Cash
Z999,Roth IRA,VOO,VANGUARD S&P 500 ETF,2,$679.70,"$1,359.40","$1,100.00",$550.00,Cash
Z123,Individual,Pending Activity,,,,$-20.00,,,

"The data and information in this spreadsheet is provided to you solely for your use..."
"""


def test_fidelity_csv_merges_accounts_and_skips_cash():
    rows = {t: (q, c) for t, q, c in parse_csv(FIDELITY_CSV)}
    assert set(rows) == {"VOO", "BRK.B"}
    q, avg = rows["VOO"]
    assert q == pytest.approx(20.261)
    assert avg == pytest.approx((18.261 * 558.38 + 2 * 550) / 20.261)


def test_bad_csv():
    with pytest.raises(ImportErrorBadFile):
        parse_csv("a,b,c\n1,2,3\n")


def test_months_to_goal():
    assert months_to_goal(155_000, 2000, 0.07, 155_000) == 0
    assert months_to_goal(0, 2000, 0.0, 24_000) == 12
    m = months_to_goal(38_000, 2000, 0.07, 155_000)
    assert 40 < m < 55
