from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles

from app.api.schemas import BacktestRequest, CompareRequest, SimulateRequest, ValidateRequest
from app.backtest.engine import BacktestResult, compare_strategies, run_backtest
from app.config import EXAMPLE_SYMBOLS
from app.data.providers import DataUnavailableError, get_ohlcv
from app.recommend.engine import recommend
from app.simulate import simulate_symbol, simulate_synthetic
from app.strategies import STRATEGY_REGISTRY, all_strategies, build_strategy
from app.validation.report import validate_symbol, validate_synthetic

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
    allow_short: bool = True,
) -> dict:
    try:
        df = get_ohlcv(symbol, period=period, interval=interval)
    except DataUnavailableError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return recommend(
        df,
        symbol=symbol,
        initial_capital=initial_capital,
        commission_bps=commission_bps,
        allow_short=allow_short,
    )


@app.post("/backtest")
def post_backtest(request: BacktestRequest) -> dict:
    try:
        df = get_ohlcv(request.symbol, period=request.period, interval=request.interval)
    except DataUnavailableError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        strategy = build_strategy(request.strategy, allow_short=request.allow_short)
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
        all_strategies(allow_short=request.allow_short),
        symbol=request.symbol,
        initial_capital=request.initial_capital,
        commission_bps=request.commission_bps,
    )
    return {"symbol": request.symbol, "ranked_by": "avg_profit_per_trade_pct", "results": [_serialize_backtest(r) for r in results]}


@app.post("/simulate")
def post_simulate(request: SimulateRequest) -> dict:
    try:
        if request.synthetic:
            return simulate_synthetic(
                strategy_name=request.strategy,
                symbol=request.symbol or "SYNTH",
                seed=request.seed,
                start_date=request.start_date,
                end_date=request.end_date,
                initial_capital=request.initial_capital,
                commission_bps=request.commission_bps,
                allow_short=request.allow_short,
            )
        if not request.symbol:
            raise HTTPException(status_code=400, detail="symbol es obligatorio salvo que synthetic=true")
        return simulate_symbol(
            request.symbol,
            strategy_name=request.strategy,
            period=request.period,
            interval=request.interval,
            start_date=request.start_date,
            end_date=request.end_date,
            initial_capital=request.initial_capital,
            commission_bps=request.commission_bps,
            allow_short=request.allow_short,
        )
    except DataUnavailableError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/validate")
def post_validate(request: ValidateRequest) -> dict:
    kwargs = dict(
        split_ratio=request.split_ratio,
        horizon=request.horizon,
        step=request.step,
        warmup=request.warmup,
        initial_capital=request.initial_capital,
        commission_bps=request.commission_bps,
        allow_short=request.allow_short,
    )
    try:
        if request.synthetic:
            return validate_synthetic(
                symbol=request.symbol or "SYNTH",
                seed=request.seed,
                start_date=request.start_date,
                end_date=request.end_date,
                **kwargs,
            )
        if not request.symbol:
            raise HTTPException(status_code=400, detail="symbol es obligatorio salvo que synthetic=true")
        return validate_symbol(
            request.symbol,
            period=request.period,
            interval=request.interval,
            start_date=request.start_date,
            end_date=request.end_date,
            **kwargs,
        )
    except DataUnavailableError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


# Serves app/static/index.html (the simulator screen) at "/". Mounted last so
# it never shadows the API routes declared above.
_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
