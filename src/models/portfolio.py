# src/models/portfolio.py
"""
Data structures for the entire application.

WHY PYDANTIC:
Regular dicts break silently. You pass a dict missing a key, code
crashes later with a confusing KeyError. Pydantic catches this at
creation time with a clear error message. Essential when agents
pass data to each other.
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
    # Negative drift = underweight = should buy more
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
    """One buy instruction."""
    ticker: str
    shares_to_buy: int = Field(ge=0)
    estimated_cost: float
    reasoning: str


class DeploymentPlan(BaseModel):
    """Complete monthly deployment recommendation."""
    date: str
    budget: float
    strategy: str
    recommendations: list[BuyRecommendation]
    cash_remaining: float = Field(ge=0)
    summary: str = ""