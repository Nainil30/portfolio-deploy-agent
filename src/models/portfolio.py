# src/models/portfolio.py
"""
Data structures for the entire application.

DOLLAR-BASED DESIGN:
All recommendations are in dollar amounts, not share counts.
Matches how Fidelity works — you enter "$500 into VOO".

TRANCHE DESIGN:
Monthly budget is split into up to 3 tranches:
  Tranche 1: Deploy immediately on payday (60%)
  Tranche 2: Reserve for dip buying (25%)
  Tranche 3: Reserve for deep dip buying (15%)
"""

from datetime import datetime
from pydantic import BaseModel, Field


class Holding(BaseModel):
    """One position in the portfolio."""
    ticker: str
    shares: float
    avg_cost: float
    current_price: float = 0.0
    current_value: float = 0.0
    target_pct: float
    actual_pct: float = 0.0
    drift: float = 0.0


class PortfolioState(BaseModel):
    """Complete portfolio snapshot."""
    timestamp: datetime = Field(default_factory=datetime.now)
    holdings: list[Holding] = []
    total_value: float = 0.0
    total_cost: float = 0.0
    total_return_pct: float = 0.0


class TickerScore(BaseModel):
    """Market attractiveness score for one ticker."""
    ticker: str
    current_price: float
    sma_20: float
    rsi: float
    drawdown_from_high_pct: float
    consecutive_red_days: int
    score: int = Field(ge=1, le=10)
    reasoning: str = ""


class BuyRecommendation(BaseModel):
    """One buy instruction in DOLLAR terms."""
    ticker: str
    dollar_amount: float = Field(ge=0)
    pct_of_budget: float = Field(ge=0)
    reasoning: str


class DipAlert(BaseModel):
    """A dip detected on a ticker — potential buy signal."""
    ticker: str
    current_price: float
    sma_20: float
    drop_from_sma_pct: float
    score: int
    is_deep_dip: bool


class DeploymentPlan(BaseModel):
    """Complete deployment recommendation for a tranche."""
    date: str
    budget: float
    strategy: str
    tranche: str = "full"       # "full", "immediate", "dip_reserve", "deep_dip_reserve"
    recommendations: list[BuyRecommendation]
    cash_remaining: float = Field(ge=0)
    summary: str = ""
    dip_alerts: list[DipAlert] = []