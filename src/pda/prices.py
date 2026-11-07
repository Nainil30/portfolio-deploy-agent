"""Price providers.

The engine depends on the small `PriceProvider` protocol, not on yfinance, so
tests and `--offline` demos use fixed prices and never touch the network.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Protocol

import yaml

from pda.config import DEMO_PRICES, normalize_ticker

log = logging.getLogger(__name__)


class PriceProvider(Protocol):
    def get_prices(self, tickers: list[str]) -> dict[str, float | None]: ...


class StaticPrices:
    """Fixed prices (tests, offline demo)."""

    def __init__(self, prices: dict[str, float]):
        self.prices = {normalize_ticker(k): float(v) for k, v in prices.items()}

    @classmethod
    def from_yaml(cls, path: Path = DEMO_PRICES) -> StaticPrices:
        with open(path, encoding="utf-8") as f:
            return cls((yaml.safe_load(f) or {}).get("prices", {}))

    def get_prices(self, tickers: list[str]) -> dict[str, float | None]:
        return {t: self.prices.get(t) for t in tickers}


class YahooPrices:
    """Latest close from Yahoo Finance (free, no key), cached for `ttl` seconds."""

    def __init__(self, aliases: dict[str, str] | None = None, ttl: int = 600):
        self.aliases = aliases or {}
        self.ttl = ttl
        self._cache: dict[str, tuple[float, float]] = {}

    def _symbol(self, ticker: str) -> str:
        return self.aliases.get(ticker, ticker.replace(".", "-"))

    def get_prices(self, tickers: list[str]) -> dict[str, float | None]:
        now = time.time()
        out: dict[str, float | None] = {}
        todo: list[str] = []
        for t in tickers:
            hit = self._cache.get(t)
            if hit and now - hit[1] < self.ttl:
                out[t] = hit[0]
            else:
                todo.append(t)
        if todo:
            fetched = self._fetch(todo)
            for t in todo:
                price = fetched.get(t)
                out[t] = price
                if price is not None:
                    self._cache[t] = (price, now)
        return out

    def _fetch(self, tickers: list[str]) -> dict[str, float | None]:
        import yfinance as yf  # imported lazily: slow import, not needed offline

        symbols = {self._symbol(t): t for t in tickers}
        result: dict[str, float | None] = {t: None for t in tickers}
        try:
            data = yf.download(
                list(symbols), period="5d", interval="1d", progress=False,
                auto_adjust=True, group_by="column", threads=True,
            )
            close = data["Close"] if not data.empty else None
            if close is not None:
                if hasattr(close, "columns"):
                    for sym, t in symbols.items():
                        if sym in close.columns:
                            series = close[sym].dropna()
                            if not series.empty:
                                result[t] = round(float(series.iloc[-1]), 4)
                else:  # single ticker -> Series
                    series = close.dropna()
                    if not series.empty:
                        result[tickers[0]] = round(float(series.iloc[-1]), 4)
        except Exception as exc:  # noqa: BLE001 - network/parsing; degrade gracefully
            log.warning("Batch price download failed: %s", exc)

        # Retry stragglers one by one (new listings, odd symbols).
        for sym, t in symbols.items():
            if result[t] is None:
                try:
                    price = yf.Ticker(sym).fast_info.get("last_price")
                    if price and price > 0:
                        result[t] = round(float(price), 4)
                except Exception as exc:  # noqa: BLE001
                    log.info("No price for %s (%s): %s", t, sym, exc)
        return result
