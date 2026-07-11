# src/tools/database.py
"""
SQLite storage for portfolio history and deployment tracking.

WHY SQLITE:
Comes with Python. No server to install. Just a file.
Stores transaction history so the dashboard can show trends
over months. Without this, every run is amnesia.
"""

import sqlite3
import json
from datetime import datetime

from src.utils.config_loader import DB_PATH


def _connect() -> sqlite3.Connection:
    """Get database connection. Creates file if needed."""
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
            budget REAL NOT NULL,
            plan_json TEXT NOT NULL,
            status TEXT DEFAULT 'recommended'
        );
    """)
    conn.commit()
    conn.close()


def save_snapshot(total_value: float, total_cost: float, holdings: list[dict]) -> None:
    """Save portfolio state for historical tracking."""
    conn = _connect()
    conn.execute(
        "INSERT INTO snapshots (date, total_value, total_cost, holdings_json) VALUES (?,?,?,?)",
        (datetime.now().isoformat(), total_value, total_cost, json.dumps(holdings)),
    )
    conn.commit()
    conn.close()


def save_deployment(budget: float, plan: dict) -> int:
    """Save a deployment plan. Returns row ID."""
    conn = _connect()
    cur = conn.execute(
        "INSERT INTO deployments (date, budget, plan_json) VALUES (?,?,?)",
        (datetime.now().isoformat(), budget, json.dumps(plan)),
    )
    row_id = cur.lastrowid
    conn.commit()
    conn.close()
    return row_id


def log_transaction(ticker: str, shares: float, price: float) -> None:
    """Record a confirmed buy."""
    conn = _connect()
    conn.execute(
        "INSERT INTO transactions (date, ticker, shares, price, total) VALUES (?,?,?,?,?)",
        (datetime.now().isoformat(), ticker, shares, price, round(shares * price, 2)),
    )
    conn.commit()
    conn.close()


def get_deployments() -> list[dict]:
    """All past deployments for dashboard."""
    conn = _connect()
    rows = conn.execute("SELECT * FROM deployments ORDER BY date DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_snapshots() -> list[dict]:
    """All snapshots for trend chart."""
    conn = _connect()
    rows = conn.execute("SELECT * FROM snapshots ORDER BY date ASC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# Create tables on first import
init_db()