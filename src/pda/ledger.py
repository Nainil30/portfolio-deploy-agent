"""SQLite ledger: an append-only list of transactions.

Holdings are *derived* from transactions instead of being edited in place.
That gives us undo, an audit trail ("what did I buy in March?"), and lets a
broker CSV import reset everything without losing history (old rows are
voided, not deleted, so even an import can be undone).
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from pda.models import Plan

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    ticker     TEXT NOT NULL,
    kind       TEXT NOT NULL CHECK (kind IN ('buy', 'sell', 'import')),
    shares     REAL NOT NULL CHECK (shares > 0),
    price      REAL NOT NULL CHECK (price >= 0),
    amount     REAL NOT NULL,
    batch      TEXT NOT NULL,
    note       TEXT DEFAULT '',
    voided_by  TEXT
);
CREATE INDEX IF NOT EXISTS ix_tx_batch ON transactions(batch);

CREATE TABLE IF NOT EXISTS plans (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    month      TEXT NOT NULL,
    kind       TEXT NOT NULL,
    amount     REAL NOT NULL,
    payload    TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'proposed',   -- proposed | executed | skipped
    batch      TEXT
);

CREATE TABLE IF NOT EXISTS snapshots (
    day         TEXT PRIMARY KEY,
    total_value REAL NOT NULL,
    total_cost  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
    key TEXT PRIMARY KEY,
    ts  TEXT NOT NULL
);
"""


@dataclass
class Tx:
    id: int
    ts: str
    ticker: str
    kind: str
    shares: float
    price: float
    amount: float
    batch: str
    note: str


@dataclass
class Holding:
    shares: float
    cost: float


class LedgerError(ValueError):
    pass


class Ledger:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)

    @contextmanager
    def _tx(self):
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # ── transactions ────────────────────────────────────────────────────
    def record(self, rows: list[tuple[str, str, float, float]], note: str = "") -> str:
        """Insert (ticker, kind, shares, price) rows as one batch. Returns the batch id."""
        if not rows:
            raise LedgerError("Nothing to record")
        batch = uuid.uuid4().hex[:10]
        ts = datetime.now().isoformat(timespec="seconds")
        current = self.holdings()
        with self._tx() as c:
            for ticker, kind, shares, price in rows:
                if shares <= 0:
                    raise LedgerError(f"{ticker}: shares must be positive")
                if kind == "sell":
                    held = current.get(ticker, Holding(0, 0)).shares
                    if shares > held + 1e-9:
                        raise LedgerError(f"Cannot sell {shares:g} {ticker}; you hold {held:g}")
                c.execute(
                    "INSERT INTO transactions (ts, ticker, kind, shares, price, amount, batch, note)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (ts, ticker, kind, shares, price, round(shares * price, 2), batch, note),
                )
        return batch

    def replace_with_import(self, rows: list[tuple[str, float, float]], note: str = "import") -> str:
        """Reset holdings to a broker snapshot: void every active row, insert imports."""
        if not rows:
            raise LedgerError("Import file had no positions")
        batch = uuid.uuid4().hex[:10]
        ts = datetime.now().isoformat(timespec="seconds")
        with self._tx() as c:
            c.execute("UPDATE transactions SET voided_by = ? WHERE voided_by IS NULL", (batch,))
            for ticker, shares, avg_cost in rows:
                c.execute(
                    "INSERT INTO transactions (ts, ticker, kind, shares, price, amount, batch, note)"
                    " VALUES (?, ?, 'import', ?, ?, ?, ?, ?)",
                    (ts, ticker, shares, avg_cost, round(shares * avg_cost, 2), batch, note),
                )
        return batch

    def undo_last(self) -> list[Tx]:
        """Remove the most recent batch (and restore anything it voided)."""
        row = self._conn.execute(
            "SELECT batch FROM transactions WHERE voided_by IS NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if not row:
            return []
        batch = row["batch"]
        removed = self._txs("WHERE batch = ? AND voided_by IS NULL", (batch,))
        with self._tx() as c:
            c.execute("DELETE FROM transactions WHERE batch = ?", (batch,))
            c.execute("UPDATE transactions SET voided_by = NULL WHERE voided_by = ?", (batch,))
            c.execute("UPDATE plans SET status = 'proposed', batch = NULL WHERE batch = ?", (batch,))
        return removed

    def _txs(self, where: str, params: tuple = ()) -> list[Tx]:
        cur = self._conn.execute(
            f"SELECT id, ts, ticker, kind, shares, price, amount, batch, note FROM transactions {where}",
            params,
        )
        return [Tx(**dict(r)) for r in cur.fetchall()]

    def recent(self, limit: int = 15) -> list[Tx]:
        return self._txs("WHERE voided_by IS NULL ORDER BY id DESC LIMIT ?", (limit,))

    def holdings(self) -> dict[str, Holding]:
        """Replay active transactions. Sells reduce cost at average cost."""
        out: dict[str, Holding] = {}
        for tx in self._txs("WHERE voided_by IS NULL ORDER BY id"):
            h = out.setdefault(tx.ticker, Holding(0.0, 0.0))
            if tx.kind in ("buy", "import"):
                h.shares += tx.shares
                h.cost += tx.amount
            else:
                avg = h.cost / h.shares if h.shares else 0.0
                h.shares -= tx.shares
                h.cost -= avg * tx.shares
        return {t: h for t, h in out.items() if h.shares > 1e-9}

    def sell_count(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM transactions WHERE kind = 'sell' AND voided_by IS NULL"
        ).fetchone()
        return int(row["n"])

    def invested_since(self, since: date) -> float:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS s FROM transactions "
            "WHERE kind = 'buy' AND voided_by IS NULL AND ts >= ?",
            (since.isoformat(),),
        ).fetchone()
        return float(row["s"])

    # ── plans ───────────────────────────────────────────────────────────
    def save_plan(self, plan: Plan) -> int:
        with self._tx() as c:
            cur = c.execute(
                "INSERT INTO plans (created_at, month, kind, amount, payload) VALUES (?, ?, ?, ?, ?)",
                (
                    plan.created_at.isoformat(timespec="seconds"),
                    plan.created_at.strftime("%Y-%m"),
                    plan.kind,
                    plan.amount,
                    json.dumps(plan.as_dict()),
                ),
            )
        plan.id = int(cur.lastrowid)
        return plan.id

    def get_plan(self, plan_id: int) -> tuple[Plan, str] | None:
        row = self._conn.execute("SELECT payload, status FROM plans WHERE id = ?", (plan_id,)).fetchone()
        if not row:
            return None
        return Plan.from_dict(json.loads(row["payload"]), plan_id), row["status"]

    def set_plan_status(self, plan_id: int, status: str, batch: str | None = None) -> None:
        with self._tx() as c:
            c.execute("UPDATE plans SET status = ?, batch = ? WHERE id = ?", (status, batch, plan_id))

    def monthly_plan_executed(self, month: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM plans WHERE month = ? AND kind = 'monthly' AND status = 'executed' LIMIT 1",
            (month,),
        ).fetchone()
        return row is not None

    # ── snapshots & alerts ──────────────────────────────────────────────
    def save_snapshot(self, day: date, value: float, cost: float) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT INTO snapshots (day, total_value, total_cost) VALUES (?, ?, ?) "
                "ON CONFLICT(day) DO UPDATE SET total_value = excluded.total_value, "
                "total_cost = excluded.total_cost",
                (day.isoformat(), value, cost),
            )

    def snapshots(self, limit: int = 400) -> list[tuple[str, float, float]]:
        rows = self._conn.execute(
            "SELECT day, total_value, total_cost FROM snapshots ORDER BY day DESC LIMIT ?", (limit,)
        ).fetchall()
        return [(r["day"], r["total_value"], r["total_cost"]) for r in reversed(rows)]

    def peak(self) -> tuple[str, float] | None:
        """Highest value *net of contributions*: we compare value minus cost basis
        so new deposits don't look like gains and a pause in deposits doesn't
        look like a loss."""
        row = self._conn.execute(
            "SELECT day, total_value - total_cost AS g FROM snapshots ORDER BY g DESC LIMIT 1"
        ).fetchone()
        return (row["day"], float(row["g"])) if row else None

    def alert_sent(self, key: str) -> bool:
        return self._conn.execute("SELECT 1 FROM alerts WHERE key = ?", (key,)).fetchone() is not None

    def mark_alert(self, key: str) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT OR IGNORE INTO alerts (key, ts) VALUES (?, ?)",
                (key, datetime.now().isoformat(timespec="seconds")),
            )
