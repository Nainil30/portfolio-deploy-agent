"""Goal projections, drawdown detection and stress tests.

Behavioural guardrails matter more than math: the plan only works if you
keep buying through a 30% drop. These helpers turn scary numbers into
"here is what the plan says to do".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from pda.models import Snapshot


@dataclass
class Projection:
    annual_return: float
    months: int | None  # None = not reached within 50 years

    def eta(self, start: date) -> date | None:
        if self.months is None:
            return None
        y, m = divmod(start.month - 1 + self.months, 12)
        return date(start.year + y, m + 1, 1)


def months_to_goal(current: float, monthly: float, annual_return: float, goal: float) -> int | None:
    if current >= goal:
        return 0
    r = (1 + annual_return) ** (1 / 12) - 1
    value = current
    for month in range(1, 601):
        value = value * (1 + r) + monthly
        if value >= goal:
            return month
    return None


def project(current: float, monthly: float, goal: float, base_return: float) -> list[Projection]:
    rates = sorted({0.04, round(base_return, 3), 0.10})
    return [Projection(r, months_to_goal(current, monthly, r, goal)) for r in rates]


@dataclass
class Drawdown:
    peak_day: str
    peak_gain: float
    current_gain: float

    @property
    def dollars(self) -> float:
        return max(0.0, self.peak_gain - self.current_gain)

    def pct(self, total_cost: float) -> float:
        base = total_cost + self.peak_gain
        return (self.dollars / base * 100) if base > 0 else 0.0


SCENARIOS: dict[str, dict[str, float]] = {
    # bucket/ai shocks in %, applied to current values
    "AI sell-off (2022-style)": {"ai": -40, "non_ai_equity": -15, "gold": 5},
    "Broad bear market (-30%)": {"ai": -35, "non_ai_equity": -25, "gold": 10},
    "Mild correction (-12%)": {"ai": -18, "non_ai_equity": -8, "gold": 2},
}


@dataclass
class StressResult:
    name: str
    loss: float
    loss_pct: float
    extra_shares_pct: float  # how much more stock the monthly buy gets at these prices


def stress_test(snap: Snapshot) -> list[StressResult]:
    out = []
    for name, shocks in SCENARIOS.items():
        loss = 0.0
        for p in snap.positions.values():
            if p.bucket == "gold":
                shock = shocks["gold"]
            elif p.ai:
                shock = shocks["ai"]
            else:
                shock = shocks["non_ai_equity"]
            loss += p.value * shock / 100
        pct = loss / snap.total_value * 100 if snap.total_value else 0.0
        extra = (1 / (1 + pct / 100) - 1) * 100 if pct > -100 else 0.0
        out.append(StressResult(name, loss, pct, extra))
    return out
