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
    commission_bps: float | None = Field(
        None, description="Basis points por operación; si se omite usa un promedio realista según el tipo de instrumento (acciones, cripto, forex, etc.)"
    )
    allow_short: bool = True


class CompareRequest(BaseModel):
    symbol: str = Field(..., examples=["AAPL", "BTC-USD", "EURUSD=X"])
    period: str = "2y"
    interval: str = "1d"
    initial_capital: float = 10_000.0
    commission_bps: float | None = Field(
        None, description="Basis points por operación; si se omite usa un promedio realista según el tipo de instrumento (acciones, cripto, forex, etc.)"
    )
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
    commission_bps: float | None = Field(
        None, description="Basis points por operación; si se omite usa un promedio realista según el tipo de instrumento (acciones, cripto, forex, etc.)"
    )
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
    commission_bps: float | None = Field(
        None, description="Basis points por operación; si se omite usa un promedio realista según el tipo de instrumento (acciones, cripto, forex, etc.)"
    )
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


class OpportunitiesRequest(BaseModel):
    symbols: list[str] | None = Field(
        None, description="Ej. ['AAPL', 'MSFT', 'BTC-USD']. Si se omite y synthetic=false, usa el universo de ejemplo"
    )
    synthetic: bool = False
    seed: int = 42
    period: str = "2y"
    interval: str = "1d"
    initial_capital: float = 10_000.0
    commission_bps: float | None = Field(
        None, description="Basis points por operación; si se omite usa un promedio realista según el tipo de instrumento (acciones, cripto, forex, etc.)"
    )
    allow_short: bool = True
    with_earnings: bool = Field(False, description="Ajusta cada símbolo con el historial de earnings (Finnhub)")
    with_news: bool = Field(False, description="Ajusta cada símbolo con el sentimiento de noticias (Alpha Vantage)")
    top_n: int = Field(5, description="Cuántos símbolos mostrar en cada lista (compra/venta)")


class PortfolioSimulateRequest(BaseModel):
    start_date: str = Field(..., description="ISO, ej. 2026-01-01. Fecha desde la que se simula día a día")
    end_date: str | None = Field(None, description="ISO. Si se omite, usa hasta el último dato disponible")
    symbols: list[str] | None = Field(
        None, description="Universo del que se selecciona el portafolio. Si se omite y synthetic=false, usa el universo de ejemplo"
    )
    synthetic: bool = False
    seed: int = 42
    portfolio_size: int = Field(5, description="Cuántos símbolos selecciona automáticamente el portafolio")
    period: str = "3y"
    interval: str = "1d"
    initial_capital: float = 10_000.0
    commission_bps: float | None = Field(
        None, description="Basis points por operación; si se omite usa un promedio realista según el tipo de instrumento (acciones, cripto, forex, etc.)"
    )
    allow_short: bool = True
    step: int = Field(1, description="Cada cuántos días se recalcula la señal (1 = todos los días)")
    min_confidence_pct: float = Field(
        55.0,
        description="Confianza mínima del ensemble (%) para elegir un símbolo o voltear su posición; por debajo se trata como HOLD",
    )
    adaptive_learning: bool = Field(
        True,
        description="Si está activo, una racha de operaciones subóptimas en retrospectiva (ver hindsight) sube el umbral de confianza sobre la marcha",
    )


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
    commission_bps: float | None = Field(
        None, description="Basis points por operación; si se omite usa un promedio realista según el tipo de instrumento (acciones, cripto, forex, etc.)"
    )
    allow_short: bool = True
