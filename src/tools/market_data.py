# src/tools/market_data.py
"""
Fetch market data from Yahoo Finance and compute technical indicators.

WHY YFINANCE: Free. No API key. No sign-up. Reliable for daily data.

We compute RSI ourselves instead of using pandas-ta because
pandas-ta is abandoned and fails on Python 3.12+.
"""

import yfinance as yf
import pandas as pd

from src.models.portfolio import TickerScore


def _compute_rsi(prices: pd.Series, period: int = 14) -> float:
    """
    Relative Strength Index (RSI) — momentum indicator.

    HOW IT WORKS:
    - Track daily price changes
    - Separate gains from losses
    - Average gains vs average losses over 'period' days
    - RSI = 100 - (100 / (1 + avg_gain/avg_loss))

    RSI < 30 = oversold (potentially good buy)
    RSI > 70 = overbought (potentially expensive)
    """
    delta = prices.diff()
    gains = delta.where(delta > 0, 0.0)
    losses = -delta.where(delta < 0, 0.0)

    avg_gain = gains.rolling(window=period).mean().iloc[-1]
    avg_loss = losses.rolling(window=period).mean().iloc[-1]

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def _safe_float(value) -> float:
    """
    Safely convert yfinance output to a plain float.

    WHY THIS EXISTS:
    yfinance 0.2.40+ sometimes returns a Series or numpy array
    instead of a scalar, even for single values. This caused
    the 'float() argument must be a Series' crash on VIX.
    .squeeze() collapses any single-element container to a scalar.
    """
    if isinstance(value, pd.Series):
        return float(value.squeeze())
    if isinstance(value, pd.DataFrame):
        return float(value.squeeze())
    return float(value)


def get_current_prices(tickers: list[str]) -> dict[str, float]:
    """
    Batch-fetch latest closing prices.
    Returns {ticker: price} dict.
    """
    if not tickers:
        return {}

    data = yf.download(
        " ".join(tickers),
        period="5d",
        interval="1d",
        progress=False,
        auto_adjust=True,
    )

    prices = {}

    if len(tickers) == 1:
        # FIXED: use _safe_float to handle Series/scalar ambiguity
        prices[tickers[0]] = round(_safe_float(data["Close"].iloc[-1]), 2)
    else:
        for t in tickers:
            try:
                prices[t] = round(_safe_float(data["Close"][t].iloc[-1]), 2)
            except (KeyError, IndexError):
                prices[t] = 0.0
    return prices


def analyze_ticker(ticker: str) -> TickerScore:
    """
    Compute attractiveness score for a ticker.

    SCORING (deterministic — no LLM):
      Start at 5.
      Below 20-day SMA by 3%+    → +2
      RSI < 35 (oversold)        → +2
      RSI > 70 (overbought)      → -1
      3+ red days in a row        → +1
      Drawdown > 10% from high    → +1
      Within 1% of 52-week high   → -2
      Clamp result to [1, 10].
    """
    data = yf.download(
        ticker, period="6mo", interval="1d",
        progress=False, auto_adjust=True,
    )

    if data.empty:
        return TickerScore(
            ticker=ticker, current_price=0, sma_20=0, rsi=50,
            drawdown_from_high_pct=0, consecutive_red_days=0,
            score=5, reasoning="No data",
        )

    # FIXED: .squeeze() on every column access to ensure plain Series
    close = data["Close"].squeeze()
    opens = data["Open"].squeeze()

    # FIXED: _safe_float for scalar extraction
    price = _safe_float(close.iloc[-1])
    sma_20 = _safe_float(close.rolling(20).mean().iloc[-1])
    rsi = _compute_rsi(close)
    high = _safe_float(close.max())
    drawdown = ((price - high) / high) * 100

    # Consecutive red days (close < open)
    red_days = 0
    for i in range(len(close) - 1, max(len(close) - 10, -1), -1):
        if _safe_float(close.iloc[i]) < _safe_float(opens.iloc[i]):
            red_days += 1
        else:
            break

    # Scoring
    score = 5
    reasons = []

    if price < sma_20 * 0.97:
        score += 2
        reasons.append(f"{((price / sma_20) - 1) * 100:.1f}% below 20d SMA")
    if rsi < 35:
        score += 2
        reasons.append(f"RSI oversold ({rsi:.0f})")
    elif rsi > 70:
        score -= 1
        reasons.append(f"RSI overbought ({rsi:.0f})")
    if red_days >= 3:
        score += 1
        reasons.append(f"{red_days} red days")
    if drawdown < -10:
        score += 1
        reasons.append(f"{drawdown:.1f}% from high")
    if drawdown > -1:
        score -= 2
        reasons.append("Near 52-week high")

    score = max(1, min(10, score))

    return TickerScore(
        ticker=ticker,
        current_price=round(price, 2),
        sma_20=round(sma_20, 2),
        rsi=rsi,
        drawdown_from_high_pct=round(drawdown, 1),
        consecutive_red_days=red_days,
        score=score,
        reasoning="; ".join(reasons) if reasons else "Normal conditions",
    )


def get_vix() -> dict:
    """VIX = market fear gauge. Higher = more fear = potentially better buy window."""
    data = yf.download("^VIX", period="5d", progress=False, auto_adjust=True)

    if data.empty:
        return {"vix": 20.0, "mood": "calm"}

    # FIXED: .squeeze() twice — once for column, once for value
    close = data["Close"].squeeze()
    vix = _safe_float(close.iloc[-1])

    return {
        "vix": round(vix, 1),
        "mood": "fearful" if vix > 25 else "cautious" if vix > 18 else "calm",
    }