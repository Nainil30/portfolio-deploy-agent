# src/tools/market_data.py
"""
Fetch market data from Yahoo Finance.

WHY YFINANCE:
Free. No API key. No sign-up. Reliable for daily data.
15-minute delay on intraday, but we only need daily closes
for DCA decisions, so this is fine.
"""

import yfinance as yf
import pandas_ta as ta

from src.models.portfolio import TickerScore


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
        # yfinance returns flat columns for single ticker
        prices[tickers[0]] = round(float(data["Close"].iloc[-1]), 2)
    else:
        for t in tickers:
            try:
                prices[t] = round(float(data["Close"][t].iloc[-1]), 2)
            except (KeyError, IndexError):
                prices[t] = 0.0
    return prices


def analyze_ticker(ticker: str) -> TickerScore:
    """
    Compute attractiveness score for a ticker.

    SCORING (deterministic — no LLM involved):
      Start at 5.
      Below 20-day SMA by 3%+    → +2
      RSI < 35 (oversold)        → +2
      RSI > 70 (overbought)      → -1
      3+ red days in a row        → +1
      Drawdown > 10% from high    → +1
      Within 1% of 52-week high   → -2
      Clamp result to [1, 10].
    """
    data = yf.download(ticker, period="6mo", interval="1d", progress=False, auto_adjust=True)

    if data.empty:
        return TickerScore(
            ticker=ticker, current_price=0, sma_20=0, rsi=50,
            drawdown_from_high_pct=0, consecutive_red_days=0,
            score=5, reasoning="No data",
        )

    close = data["Close"].squeeze()
    opens = data["Open"].squeeze()
    price = float(close.iloc[-1])

    # Indicators
    sma_20 = float(close.rolling(20).mean().iloc[-1])
    rsi_s = ta.rsi(close, length=14)
    rsi = float(rsi_s.iloc[-1]) if rsi_s is not None else 50.0
    high = float(close.max())
    drawdown = ((price - high) / high) * 100

    # Consecutive red days
    red_days = 0
    for i in range(len(close) - 1, max(len(close) - 10, -1), -1):
        if close.iloc[i] < opens.iloc[i]:
            red_days += 1
        else:
            break

    # Score
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
        rsi=round(rsi, 1),
        drawdown_from_high_pct=round(drawdown, 1),
        consecutive_red_days=red_days,
        score=score,
        reasoning="; ".join(reasons) if reasons else "Normal conditions",
    )


def get_vix() -> dict:
    """VIX = market fear gauge. Higher = more fear = better buy window."""
    data = yf.download("^VIX", period="5d", progress=False, auto_adjust=True)
    vix = float(data["Close"].iloc[-1]) if not data.empty else 20.0
    return {
        "vix": round(vix, 1),
        "mood": "fearful" if vix > 25 else "cautious" if vix > 18 else "calm",
    }