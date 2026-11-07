"""Currency formatting shared by every layer (set once from strategy.profile.currency)."""

_SYMBOL = "$"


def set_currency(symbol: str) -> None:
    global _SYMBOL
    _SYMBOL = symbol or "$"


def money(x: float, cents: bool = False) -> str:
    sign = "-" if x < 0 else ""
    body = f"{abs(x):,.2f}" if cents else f"{abs(x):,.0f}"
    return f"{sign}{_SYMBOL}{body}"
