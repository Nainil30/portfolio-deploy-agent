# src/tools/market_data.py
"""
Fetch market data from Yahoo Finance and compute technical indicators.
"""

import yfinance as yf
import pandas as pd
import numpy as np

from src.models.portfolio import TickerScore


def _to_series(column_data) -> pd.Series:
    """
    Safely convert any yfinance column output to a plain pandas Series.

    WHY THIS EXISTS:
    yfinance returns different shapes depending on version:
      - Sometimes a Series
      - Sometimes a DataFrame with MultiIndex columns
      - Sometimes a DataFrame with single column
    squeeze() can over-collapse to a scalar.
    This function always returns a proper Series.
    """
    if isinstance(column_data, pd.DataFrame):
        # Flatten multi-level columns if needed
        if column_data.shape[1] == 1:
            return column_data.iloc[:, 0]
        return column_data.iloc[:, 0]
    if isinstance(column_data, pd.Series):
        return column_data
    # If somehow a scalar, wrap it
    return pd.Series([column_data])


def _last_value(series) -> float:
    """
    Get the last value from a Series, DataFrame, or scalar.
    Always returns a plain Python float.
    """
    if isinstance(series, (int, float, np.integer, np.floating)):
        return float(series)
    if isinstance(series, pd.DataFrame):
        return float(series.iloc[-1, 0])
    if isinstance(series, pd.Series):
        return float(series.iloc[-1])
    return float(series)


def _compute_rsi(prices: pd.Series, period: int = 14) -> float:
    """
    Relative Strength Index (RSI).
    RSI < 30 = oversold (good buy), RSI > 70 = overbought.
    """
    delta = prices.diff()
    gains = delta.where(delta > 0, 0.0)
    losses = -delta.where(delta < 0, 0.0)

    avg_gain = _last_value(gains.rolling(window=period).mean())
    avg_loss = _last_value(losses.rolling(window=period).mean())

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return round(100 - (100 / (1 + rs)), 1)


def get_current_prices(tickers: list[str]) -> dict[str, float]:
    """Batch-fetch latest closing prices."""
    if not tickers:
        return {}

    data = yf.download(
        " ".join(tickers),
        period="5d",
        interval="1d",
        progress=False,
        auto_adjust=True,
    )

    if data.empty:
        return {t: 0.0 for t in tickers}

    prices = {}
    close = data["Close"]

    if len(tickers) == 1:
        series = _to_series(close)
        prices[tickers[0]] = round(_last_value(series), 2)
    else:
        for t in tickers:
            try:
                if isinstance(close, pd.DataFrame) and t in close.columns:
                    prices[t] = round(_last_value(close[t]), 2)
                else:
                    col = _to_series(close)
                    prices[t] = round(_last_value(col), 2)
            except (KeyError, IndexError):
                prices[t] = 0.0

    return prices


def analyze_ticker(ticker: str) -> TickerScore:
    """
    Compute attractiveness score for a ticker.

    SCORING (deterministic):
      Start at 5.
      Below 20-day SMA by 3%+  -> +2
      RSI < 35 (oversold)      -> +2
      RSI > 70 (overbought)    -> -1
      3+ red days in a row     -> +1
      Drawdown > 10% from high -> +1
      Within 1% of high        -> -2
      Clamp to [1, 10].
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

    close = _to_series(data["Close"])
    opens = _to_series(data["Open"])

    price = _last_value(close)
    sma_20 = _last_value(close.rolling(20).mean())
    rsi = _compute_rsi(close)
    high = float(close.max())
    drawdown = ((price - high) / high) * 100 if high > 0 else 0

    # Consecutive red days
    red_days = 0
    for i in range(len(close) - 1, max(len(close) - 10, -1), -1):
        try:
            c = float(close.iloc[i])
            o = float(opens.iloc[i])
            if c < o:
                red_days += 1
            else:
                break
        except (IndexError, TypeError):
            break

    # Scoring
    score = 5
    reasons = []

    if sma_20 > 0 and price < sma_20 * 0.97:
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
    """VIX = market fear gauge."""
    data = yf.download("^VIX", period="5d", progress=False, auto_adjust=True)

    if data.empty:
        return {"vix": 20.0, "mood": "calm"}

    close = _to_series(data["Close"])
    vix = _last_value(close)

    return {
        "vix": round(vix, 1),
        "mood": "fearful" if vix > 25 else "cautious" if vix > 18 else "calm",
    }
