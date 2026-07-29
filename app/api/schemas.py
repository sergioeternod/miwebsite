from __future__ import annotations

from pydantic import BaseModel, Field


class BacktestRequest(BaseModel):
    symbol: str = Field(..., examples=["AAPL", "BTC-USD", "EURUSD=X"])
    strategy: str = Field(..., examples=["sma_crossover", "macd_crossover", "rsi_reversion", "bollinger_breakout"])
    period: str = "2y"
    interval: str = "1d"
    initial_capital: float = 10_000.0
    commission_bps: float = 5.0


class CompareRequest(BaseModel):
    symbol: str = Field(..., examples=["AAPL", "BTC-USD", "EURUSD=X"])
    period: str = "2y"
    interval: str = "1d"
    initial_capital: float = 10_000.0
    commission_bps: float = 5.0


