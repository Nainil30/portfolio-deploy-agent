"""Plain data structures shared by every layer.

Dataclasses (not Pydantic) keep the core dependency-free and fast to test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class TargetSpec:
    ticker: str
    pct: float
    bucket: str  # core_etf | etf | gold | stock | untargeted
    ai: bool = False


@dataclass
class Position:
    ticker: str
    shares: float
    cost_basis: float
    price: float | None
    target_pct: float
    bucket: str
    ai: bool
    value: float = 0.0
    actual_pct: float = 0.0
    price_is_stale: bool = False  # True when we had to fall back to cost basis

    @property
    def gap_pct(self) -> float:
        """Percentage points BELOW target (positive = underweight)."""
        return round(self.target_pct - self.actual_pct, 2)

    @property
    def gain(self) -> float:
        return self.value - self.cost_basis

    @property
    def gain_pct(self) -> float:
        return (self.gain / self.cost_basis * 100) if self.cost_basis > 0 else 0.0


@dataclass
class Snapshot:
    positions: dict[str, Position]
    total_value: float
    total_cost: float
    missing_prices: list[str] = field(default_factory=list)
    as_of: datetime = field(default_factory=datetime.now)

    @property
    def gain(self) -> float:
        return self.total_value - self.total_cost

    @property
    def gain_pct(self) -> float:
        return (self.gain / self.total_cost * 100) if self.total_cost > 0 else 0.0

    def value_of(self, ticker: str) -> float:
        p = self.positions.get(ticker)
        return p.value if p else 0.0

    def bucket_pcts(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for p in self.positions.values():
            out[p.bucket] = out.get(p.bucket, 0.0) + p.actual_pct
        return out

    def ai_pct(self) -> float:
        return sum(p.actual_pct for p in self.positions.values() if p.ai)


@dataclass
class Adjustment:
    """A guardrail (or engine) decision that changed the plan, in plain English."""

    rule: str
    message: str


@dataclass
class BuyLine:
    ticker: str
    amount: float
    reason: str
    price: float | None = None

    @property
    def est_shares(self) -> float | None:
        return (self.amount / self.price) if self.price else None


@dataclass
class Plan:
    kind: str  # "monthly" | "extra"
    amount: float
    lines: list[BuyLine]
    notes: list[Adjustment] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    id: int | None = None

    @property
    def total(self) -> float:
        return round(sum(line.amount for line in self.lines), 2)

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "amount": self.amount,
            "created_at": self.created_at.isoformat(timespec="seconds"),
            "lines": [
                {"ticker": ln.ticker, "amount": ln.amount, "reason": ln.reason, "price": ln.price}
                for ln in self.lines
            ],
            "notes": [{"rule": n.rule, "message": n.message} for n in self.notes],
        }

    @classmethod
    def from_dict(cls, d: dict, plan_id: int | None = None) -> Plan:
        return cls(
            kind=d["kind"],
            amount=d["amount"],
            lines=[BuyLine(**ln) for ln in d["lines"]],
            notes=[Adjustment(**n) for n in d.get("notes", [])],
            created_at=datetime.fromisoformat(d["created_at"]),
            id=plan_id,
        )


@dataclass
class RuleCheck:
    name: str
    status: str  # "ok" | "warn"
    detail: str
