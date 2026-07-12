# src/models/portfolio.py
"""
Data structures for the entire application.

WHY PYDANTIC:
Regular dicts break silently. Pydantic catches missing or
wrong-type fields at creation time with clear error messages.
Essential when agents pass data to each other.

NOTE ON DOLLAR-BASED DESIGN:
All recommendations are in dollar amounts, not share counts.
This matches how Fidelity works — you enter "$500 into VOO"
and Fidelity buys fractional shares automatically.
No rounding waste. Every dollar gets deployed.
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
    """
    One buy instruction in DOLLAR terms.
    
    WHY DOLLARS NOT SHARES:
    Fidelity lets you buy by dollar amount. You type "$500 into VOO"
    and Fidelity figures out the fractional shares. This means:
    - No rounding waste (every dollar deployed)
    - Matches your actual workflow
    - Simpler math (no floor division edge cases)
    """
    ticker: str
    dollar_amount: float = Field(ge=0, description="How much money to put into this ticker")
    pct_of_budget: float = Field(ge=0, description="What % of monthly budget this represents")
    reasoning: str


class DeploymentPlan(BaseModel):
    """Complete monthly deployment recommendation."""
    date: str
    budget: float
    strategy: str
    recommendations: list[BuyRecommendation]
    cash_remaining: float = Field(ge=0)
    summary: str = ""