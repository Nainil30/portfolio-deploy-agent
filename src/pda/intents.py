"""Rule-based natural-language parsing. Works with zero API keys.

The LLM is optional. Common phrases ("bought 400 of nvda", "got a 5k bonus")
are handled here deterministically, which is faster, free, and can't hallucinate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pda.config import normalize_ticker


@dataclass
class Intent:
    name: str
    args: dict = field(default_factory=dict)


_AMT = r"\$?\s*(\d[\d,]*(?:\.\d+)?)\s*(k)?"
_TICKER = r"\$?([A-Za-z]{1,5}(?:[./-][A-Za-z])?)"


def parse_amount(num: str, k: str | None = None) -> float:
    value = float(num.replace(",", ""))
    return value * 1000 if k else value


_BUY = re.compile(
    rf"^(?:i\s+)?(?:just\s+)?(?:bought|buy|purchased|added|invested)\s+{_AMT}\s*(sh|shares?)?\s+(?:of\s+|in\s+|into\s+)?{_TICKER}"
    rf"(?:\s*(?:@|at)\s*\$?(\d[\d,]*(?:\.\d+)?))?\s*$",
    re.I,
)
_BUY_TICKER_FIRST = re.compile(
    rf"^(?:i\s+)?(?:bought|buy|purchased|added)\s+{_TICKER}\s+{_AMT}\s*(sh|shares?)?(?:\s*(?:@|at)\s*\$?(\d[\d,]*(?:\.\d+)?))?\s*$",
    re.I,
)
_EXTRA = re.compile(rf"(?:extra|bonus|refund|windfall|lump\s*sum|have|got|deploy|invest)\D{{0,20}}{_AMT}", re.I)
_PLAN_AMT = re.compile(rf"^(?:plan|this month|monthly)\D*{_AMT}?\s*$", re.I)

_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("sell", ("sell", "sold", "dump", "get out", "cash out", "panic")),
    ("undo", ("undo", "revert", "mistake")),
    ("guardrails", ("guardrail", "rules", "rule check")),
    ("settings", ("settings", "my plan", "config")),
    ("stress", ("stress", "crash", "bear market", "worst case", "bad year")),
    ("goal", ("goal", "155", "how long", "when will", "target value", "retire")),
    ("drift", ("drift", "underweight", "overweight", "allocation", "targets")),
    ("history", ("history", "transactions", "what did i buy", "activity")),
    ("portfolio", ("portfolio", "status", "how am i doing", "balance", "net worth", "value")),
    ("plan", ("plan", "what should i buy", "what to buy", "buy list", "this month")),
    ("help", ("help", "commands", "what can you do", "start")),
]

# Reply-keyboard buttons map straight to intents.
BUTTONS = {
    "📋 Plan": "plan",
    "💼 Portfolio": "portfolio",
    "🎯 Drift": "drift",
    "🛡 Guardrails": "guardrails",
    "🏁 Goal": "goal",
    "🧾 History": "history",
    "⚙️ Settings": "settings",
}


def parse(text: str) -> Intent | None:
    t = text.strip()
    if t in BUTTONS:
        return Intent(BUTTONS[t])

    for rx, ticker_first in ((_BUY, False), (_BUY_TICKER_FIRST, True)):
        m = rx.match(t)
        if m:
            if ticker_first:
                ticker, num, k, unit, price = m.groups()
            else:
                num, k, unit, ticker, price = m.groups()
            return Intent("buy", {
                "ticker": normalize_ticker(ticker),
                "qty": parse_amount(num, k),
                "shares": bool(unit),
                "price": float(price.replace(",", "")) if price else None,
            })

    low = t.lower()
    if any(w in low for w in ("sell", "sold", "dump", "cash out")):
        return Intent("sell")

    m = _PLAN_AMT.match(t)
    if m and m.group(1):
        return Intent("plan", {"amount": parse_amount(m.group(1), m.group(2))})

    m = _EXTRA.search(t)
    if m and not low.startswith(("plan", "/")):
        amount = parse_amount(m.group(1), m.group(2))
        if amount >= 50:
            return Intent("extra", {"amount": amount})

    for name, words in _KEYWORDS:
        if any(w in low for w in words):
            return Intent(name)
    return None
