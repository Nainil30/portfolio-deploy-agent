# src/tools/database.py
"""
SQLite storage for portfolio history, deployments, and tranche tracking.

TRANCHE TRACKING:
Each month has up to 3 tranches. The database tracks which tranches
have been deployed so the agent knows what is left to deploy.
"""

import sqlite3
import json
from datetime import datetime

from src.utils.config_loader import DB_PATH


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables. Safe to run multiple times."""
    conn = _connect()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            ticker TEXT NOT NULL,
            shares REAL NOT NULL,
            price REAL NOT NULL,
            total REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            total_value REAL NOT NULL,
            total_cost REAL NOT NULL,
            holdings_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS deployments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            month TEXT NOT NULL,
            tranche TEXT NOT NULL,
            budget REAL NOT NULL,
            plan_json TEXT NOT NULL,
            status TEXT DEFAULT 'recommended'
        );
    """)
    conn.commit()
    conn.close()


def save_snapshot(total_value: float, total_cost: float, holdings: list[dict]) -> None:
    conn = _connect()
    conn.execute(
        "INSERT INTO snapshots (date, total_value, total_cost, holdings_json) VALUES (?,?,?,?)",
        (datetime.now().isoformat(), total_value, total_cost, json.dumps(holdings)),
    )
    conn.commit()
    conn.close()


def save_deployment(budget: float, plan: dict, tranche: str = "full") -> int:
    month = datetime.now().strftime("%Y-%m")
    conn = _connect()
    cur = conn.execute(
        "INSERT INTO deployments (date, month, tranche, budget, plan_json) VALUES (?,?,?,?,?)",
        (datetime.now().isoformat(), month, tranche, budget, json.dumps(plan)),
    )
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id


def get_month_tranches(month: str | None = None) -> list[dict]:
    """Get all tranches deployed this month."""
    if month is None:
        month = datetime.now().strftime("%Y-%m")
    conn = _connect()
    rows = conn.execute(
        "SELECT * FROM deployments WHERE month = ? ORDER BY date ASC",
        (month,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_deployed_tranches_this_month() -> set[str]:
    """Which tranches have already been deployed this month."""
    tranches = get_month_tranches()
    return {t["tranche"] for t in tranches}


def get_deployments() -> list[dict]:
    conn = _connect()
    rows = conn.execute("SELECT * FROM deployments ORDER BY date DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_snapshots() -> list[dict]:
    conn = _connect()
    rows = conn.execute("SELECT * FROM snapshots ORDER BY date ASC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def log_transaction(ticker: str, shares: float, price: float) -> None:
    conn = _connect()
    conn.execute(
        "INSERT INTO transactions (date, ticker, shares, price, total) VALUES (?,?,?,?,?)",
        (datetime.now().isoformat(), ticker, shares, price, round(shares * price, 2)),
    )
    conn.commit()
    conn.close()


init_db()