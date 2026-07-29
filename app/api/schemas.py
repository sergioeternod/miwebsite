from __future__ import annotations

from pydantic import BaseModel, Field


class BacktestRequest(BaseModel):
    symbol: str = Field(..., examples=["AAPL", "BTC-USD", "EURUSD=X"])
    strategy: str = Field(
        ..., examples=["sma_crossover", "macd_crossover", "rsi_reversion", "bollinger_breakout", "trend_confirmation"]
    )
    period: str = "2y"
    interval: str = "1d"
    initial_capital: float = 10_000.0
    commission_bps: float = 5.0
    allow_short: bool = True


class CompareRequest(BaseModel):
    symbol: str = Field(..., examples=["AAPL", "BTC-USD", "EURUSD=X"])
    period: str = "2y"
    interval: str = "1d"
    initial_capital: float = 10_000.0
    commission_bps: float = 5.0
    allow_short: bool = True


class SimulateRequest(BaseModel):
    symbol: str | None = Field(None, description="Omitir si synthetic=true")
    strategy: str | None = Field(None, description="Si se omite, corre y rankea todas")
    synthetic: bool = False
    seed: int = 42
    period: str = "2y"
    interval: str = "1d"
    start_date: str | None = Field(None, description="ISO, ej. 2023-06-01. Tiene prioridad sobre 'period'")
    end_date: str | None = Field(None, description="ISO, ej. 2023-09-30")
    initial_capital: float = 10_000.0
    commission_bps: float = 5.0
    allow_short: bool = True


class RankRequest(BaseModel):
    symbols: list[str] | None = Field(None, description="Ej. ['AAPL', 'MSFT', 'BTC-USD']. Omitir si synthetic=true")
    synthetic: bool = False
    seed: int = 42
    period: str = "2y"
    interval: str = "1d"
    start_date: str | None = Field(None, description="ISO, ej. 2023-06-01. Tiene prioridad sobre 'period'")
    end_date: str | None = Field(None, description="ISO, ej. 2023-09-30")
    initial_capital: float = 10_000.0
    commission_bps: float = 5.0
    allow_short: bool = True


class ScreenRequest(BaseModel):
    symbols: list[str] | None = Field(
        None, description="Ej. ['AAPL', 'MSFT', 'BTC-USD']. Si se omite y synthetic=false, usa el universo de ejemplo"
    )
    synthetic: bool = False
    seed: int = 42
    period: str = "2y"
    interval: str = "1d"
    top_n: int = Field(5, description="Cuántos símbolos mostrar por ventana")


class ValidateRequest(BaseModel):
    symbol: str | None = Field(None, description="Omitir si synthetic=true")
    synthetic: bool = False
    seed: int = 42
    period: str = "2y"
    interval: str = "1d"
    start_date: str | None = Field(None, description="ISO, ej. 2023-06-01. Tiene prioridad sobre 'period'")
    end_date: str | None = Field(None, description="ISO, ej. 2023-09-30")
    split_ratio: float = Field(0.5, description="Fracción del histórico usada como periodo 'expectativa'")
    horizon: int = Field(10, description="Barras hacia adelante para medir el retorno real de cada recomendación")
    step: int = Field(10, description="Separación en barras entre evaluaciones del motor de recomendaciones")
    warmup: int = Field(110, description="Barras iniciales antes de empezar a evaluar recomendaciones")
    initial_capital: float = 10_000.0
    commission_bps: float = 5.0
    allow_short: bool = True
