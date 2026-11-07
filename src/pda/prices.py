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
        """US class shares use a dash on Yahoo (BRK.B -> BRK-B); exchange
        suffixes keep the dot (RELIANCE.NS, SHOP.TO)."""
        if ticker in self.aliases:
            return self.aliases[ticker]
        base, dot, suffix = ticker.rpartition(".")
        if dot and len(suffix) == 1 and base.isalpha():
            return f"{base}-{suffix}"
        return ticker

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

    @staticmethod
    def _download(symbols: dict[str, str], result: dict[str, float | None]) -> None:
        """One batched Yahoo request; fills result[ticker] for symbols that returned data."""
        import yfinance as yf  # imported lazily: slow import, not needed offline

        if not symbols:
            return
        try:
            data = yf.download(
                list(symbols), period="5d", interval="1d", progress=False,
                auto_adjust=True, group_by="column", threads=True,
            )
        except Exception as exc:  # noqa: BLE001 - network/parsing; degrade gracefully
            log.warning("Price download failed: %s", exc)
            return
        if data.empty:
            return
        close = data["Close"]
        if hasattr(close, "columns"):
            for sym, t in symbols.items():
                if sym in close.columns:
                    series = close[sym].dropna()
                    if not series.empty:
                        result[t] = round(float(series.iloc[-1]), 4)
        else:  # single ticker -> Series
            series = close.dropna()
            if not series.empty:
                result[next(iter(symbols.values()))] = round(float(series.iloc[-1]), 4)

    def _fetch(self, tickers: list[str]) -> dict[str, float | None]:
        result: dict[str, float | None] = {t: None for t in tickers}
        self._download({self._symbol(t): t for t in tickers}, result)
        # One-letter suffixes are ambiguous (BRK.B is BRK-B on Yahoo, but VOD.L
        # stays VOD.L), so retry anything missing with the literal ticker.
        retry = {t: t for t in tickers if result[t] is None and self._symbol(t) != t}
        self._download(retry, result)
        for t in tickers:
            if result[t] is None:
                log.info("No price for %s", t)
        return result
