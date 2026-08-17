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
    with_valuation: bool = Field(False, description="Ajusta cada acción con su valuación por múltiplos (P/E de Yahoo, sin API key; solo acciones)")
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
    allow_short: bool = Field(
        False,
        description="Posiciones en corto desactivadas por defecto: perdieron contra long-only en 6 de 6 ventanas históricas validadas (incluida 2007-2010)",
    )
    step: int = Field(1, description="Cada cuántos días se recalcula la señal (1 = todos los días)")
    min_confidence_pct: float = Field(
        55.0,
        description="Confianza mínima del ensemble (%) para elegir un símbolo o voltear su posición; por debajo se trata como HOLD",
    )
    adaptive_learning: bool = Field(
        True,
        description="Si está activo, una racha de operaciones subóptimas en retrospectiva (ver hindsight) sube el umbral de confianza sobre la marcha",
    )
    with_earnings: bool = Field(
        False,
        description="Al elegir el portafolio, ajusta la confianza con el historial de earnings (Finnhub) — solo afecta acciones individuales, no cripto/forex/commodities/índices",
    )
    with_news: bool = Field(
        False,
        description="Al elegir el portafolio, ajusta la confianza con el sentimiento de noticias recientes (Alpha Vantage) — solo afecta acciones individuales",
    )
    max_per_asset_class: int | None = Field(
        None,
        description="Máximo de símbolos que pueden venir de la misma clase de activo. Si se omite: 2 en símbolos reales, sin límite (None) en sintético",
    )
    risk_parity_sizing: bool = Field(
        True,
        description="Si está activo, reparte el capital por volatilidad inversa (risk parity) en vez de partes iguales",
    )
    stop_loss_pct: float | None = Field(
        15.0,
        description="Cierra una posición si pierde más de este % desde que se abrió, sin importar la señal técnica. None para desactivarlo",
    )
    short_confidence_premium: float = Field(
        0.0,
        description="Puntos de confianza extra que un SELL necesita (sobre min_confidence_pct) para abrir un corto — los longs no lo pagan. 0 = sin asimetría",
    )
    risk_regime_sizing: bool = Field(
        True,
        description="Reduce el tamaño de las posiciones mientras la volatilidad realizada reciente (20 barras) supera su línea base de largo plazo (100 barras) — no predice caídas, achica cuánto pegan. Activo por defecto: redujo el drawdown máximo en 6 de 6 ventanas históricas validadas (incl. 2007-2010) con delta de retorno promedio +1.17 pp (retorno por ventana mixto, 3/6)",
    )
    rebalance_months: int | None = Field(
        3,
        description="Re-selecciona el portafolio cada N meses calendario (con datos solo hasta cada frontera, sin lookahead; la rotación cobra 2x la comisión del símbolo entrante). None = una sola selección al inicio, el comportamiento clásico. Default 3: le ganó al modelo sin rebalanceo en 7 de 9 ventanas validadas (6 de ajuste + 3 vírgenes) y al buy & hold en 6 de 9",
    )
    equity_regime_tilt: bool = Field(
        True,
        description="Cuando el S&P 500 está sobre su media de 200 días en una (re)selección, restringe el universo de candidatos a acciones e índices (100% accionario en mercados alcistas); debajo de ella, vuelve el universo defensivo completo. Activo por defecto: ganó al modelo sin tilt en 6 de 9 ventanas validadas (+17.2 pp promedio) y al S&P 500 en 8 de 9, a cambio de ~4 pp más de drawdown promedio (peor caso 2023-2026: -40.7%)",
    )
    emergency_reselect: bool = Field(
        False,
        description="Frontera de emergencia: si el S&P 500 cruza su media de 200 días a mitad de un segmento (en cualquier dirección), corta el segmento ahí y re-selecciona de inmediato en vez de esperar al corte programado. Requiere rebalance_months. Desactivado por defecto, pendiente de validación",
    )
    fundamental_pe_tilt: bool = Field(
        True,
        description="Ajusta la confianza de cada acción en la (re)selección con su P/E histórico punto-en-tiempo (SEC EDGAR, con fechas de presentación — causal, sin lookahead). Solo afecta acciones. Activado por defecto (validado: gana o empata 8/9 ventanas, +2.02 pp promedio)",
    )
    max_position_weight: float | None = Field(
        None,
        description="Fracción máxima del capital en un solo símbolo (ej. 0.4); el excedente queda en efectivo (el benchmark buy & hold conserva la misma reserva para que la comparación sea justa). Acota la concentración cuando pocos candidatos superan el umbral. Desactivado por defecto, pendiente de validación",
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
