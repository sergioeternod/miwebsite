from __future__ import annotations

from dataclasses import asdict

from fastapi import FastAPI, HTTPException

from app.api.schemas import BacktestRequest, CompareRequest
from app.backtest.engine import BacktestResult, compare_strategies, run_backtest
from app.config import EXAMPLE_SYMBOLS
from app.data.providers import DataUnavailableError, get_ohlcv
from app.recommend.engine import recommend
from app.strategies import STRATEGY_REGISTRY, all_strategies, build_strategy

app = FastAPI(
    title="Trading Signals API",
    description=(
        "Backtesting, indicadores técnicos y recomendaciones de compra/venta "
        "multi-instrumento (acciones, cripto, divisas, commodities, índices). "
        "No es asesoría financiera."
    ),
    version="0.1.0",
)


def _serialize_backtest(result: BacktestResult) -> dict:
    payload = asdict(result)
    payload.pop("equity_curve", None)
    payload["equity_curve"] = [round(float(v), 4) for v in result.equity_curve.tolist()]
    return payload


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/strategies")
def list_strategies() -> dict:
    return {"strategies": list(STRATEGY_REGISTRY)}


@app.get("/symbols/examples")
def symbol_examples() -> dict:
    return {k.value: v for k, v in EXAMPLE_SYMBOLS.items()}


@app.get("/recommend/{symbol}")
def get_recommendation(
    symbol: str,
    period: str = "2y",
    interval: str = "1d",
    initial_capital: float = 10_000.0,
    commission_bps: float = 5.0,
) -> dict:
    try:
        df = get_ohlcv(symbol, period=period, interval=interval)
    except DataUnavailableError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return recommend(
        df, symbol=symbol, initial_capital=initial_capital, commission_bps=commission_bps
    )


@app.post("/backtest")
def post_backtest(request: BacktestRequest) -> dict:
    try:
        df = get_ohlcv(request.symbol, period=request.period, interval=request.interval)
    except DataUnavailableError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        strategy = build_strategy(request.strategy)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = run_backtest(
        df,
        strategy,
        symbol=request.symbol,
        initial_capital=request.initial_capital,
        commission_bps=request.commission_bps,
    )
    return _serialize_backtest(result)


@app.post("/backtest/compare")
def post_compare(request: CompareRequest) -> dict:
    try:
        df = get_ohlcv(request.symbol, period=request.period, interval=request.interval)
    except DataUnavailableError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    results = compare_strategies(
        df,
        all_strategies(),
        symbol=request.symbol,
        initial_capital=request.initial_capital,
        commission_bps=request.commission_bps,
    )
    return {"symbol": request.symbol, "ranked_by": "avg_profit_per_trade_pct", "results": [_serialize_backtest(r) for r in results]}
