"""Import holdings from a broker positions CSV (Fidelity, Schwab, Vanguard,
Zerodha-style or a plain ticker,shares,avg_cost file) or a holdings YAML.

Broker CSVs are messy (header junk, footers, "$1,234.56", money-market rows),
so the parser looks for the header row by column names instead of position.
"""

from __future__ import annotations

import csv
import io
import re

import yaml

from pda.config import normalize_ticker

SYMBOL_COLS = ("symbol", "ticker", "instrument", "stock symbol", "security symbol")
QTY_COLS = ("quantity", "shares", "qty", "qty.", "units", "share quantity")
AVG_COLS = (
    "average cost basis", "avg cost basis", "cost basis per share", "avg_cost", "average cost",
    "avg. cost", "avg cost", "average price", "avg price", "cost/share", "cost per share", "buy price",
)
TOTAL_COST_COLS = ("cost basis total", "cost basis", "total cost basis", "total cost", "invested")

# Cash / money-market sweep symbols to ignore.
CASH_SYMBOLS = {"SPAXX", "FDRXX", "FCASH", "CORE", "PENDING ACTIVITY", "SPRXX", "FZFXX"}


class ImportErrorBadFile(ValueError):
    pass


def _num(raw: str | None) -> float | None:
    if raw is None:
        return None
    s = re.sub(r"[,$\s+]", "", str(raw))
    if s in ("", "--", "n/a", "N/A"):
        return None
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except ValueError:
        return None


def _find(header: list[str], options: tuple[str, ...]) -> int | None:
    lowered = [h.strip().lower() for h in header]
    for opt in options:
        if opt in lowered:
            return lowered.index(opt)
    return None


def parse_csv(text: str) -> list[tuple[str, float, float]]:
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    header_idx = next(
        (i for i, r in enumerate(rows) if _find(r, SYMBOL_COLS) is not None and _find(r, QTY_COLS) is not None),
        None,
    )
    if header_idx is None:
        raise ImportErrorBadFile("Couldn't find a header row with Symbol and Quantity columns.")
    header = rows[header_idx]
    i_sym, i_qty = _find(header, SYMBOL_COLS), _find(header, QTY_COLS)
    i_avg, i_tot = _find(header, AVG_COLS), _find(header, TOTAL_COST_COLS)

    merged: dict[str, list[float]] = {}  # same ticker in several accounts -> merge
    for r in rows[header_idx + 1:]:
        if len(r) <= max(i_sym, i_qty):
            continue
        sym = r[i_sym].strip().rstrip("*")
        if not sym or sym.upper() in CASH_SYMBOLS or " " in sym.strip():
            continue
        qty = _num(r[i_qty])
        if not qty or qty <= 0:
            continue
        avg = _num(r[i_avg]) if i_avg is not None and i_avg < len(r) else None
        if avg is None and i_tot is not None and i_tot < len(r):
            tot = _num(r[i_tot])
            avg = tot / qty if tot else None
        t = normalize_ticker(sym)
        acc = merged.setdefault(t, [0.0, 0.0])
        acc[0] += qty
        acc[1] += qty * (avg or 0.0)

    if not merged:
        raise ImportErrorBadFile("No positions found in the CSV.")
    return [(t, q, (c / q if q else 0.0)) for t, (q, c) in merged.items()]


def parse_yaml(text: str) -> list[tuple[str, float, float]]:
    data = yaml.safe_load(text) or {}
    items = data.get("holdings", data if isinstance(data, list) else [])
    out = []
    for h in items:
        shares = float(h["shares"])
        if shares <= 0:
            continue
        avg = float(h.get("avg_cost", h.get("avg_cost_per_share", 0)))
        out.append((normalize_ticker(h["ticker"]), shares, avg))
    if not out:
        raise ImportErrorBadFile("No holdings found in the YAML.")
    return out


def parse_file(filename: str, content: bytes | str) -> list[tuple[str, float, float]]:
    text = content.decode("utf-8-sig", errors="replace") if isinstance(content, bytes) else content
    if filename.lower().endswith((".yaml", ".yml")):
        return parse_yaml(text)
    if filename.lower().endswith(".csv"):
        return parse_csv(text)
    raise ImportErrorBadFile("Send a .csv (broker positions export, or ticker,shares,avg_cost) or a .yaml holdings file.")
