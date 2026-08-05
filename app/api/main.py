from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles

load_dotenv()  # lee .env si existe (API keys como FINNHUB_API_KEY); no sobreescribe variables ya definidas en el entorno

from app.api.schemas import (
    BacktestRequest,
    CompareRequest,
    OpportunitiesRequest,
    PortfolioSimulateRequest,
    RankRequest,
    ScreenRequest,
    SimulateRequest,
    ValidateRequest,
)
from app.backtest.engine import BacktestResult, compare_strategies, run_backtest
from app.config import EXAMPLE_SYMBOLS
from app.data.alphavantage_client import AlphaVantageUnavailableError
from app.data.finnhub_client import FinnhubUnavailableError
from app.data.providers import DataUnavailableError, get_ohlcv
from app.fundamentals.earnings import apply_earnings_overlay, earnings_report
from app.fundamentals.news_sentiment import apply_news_overlay, news_report
from app.opportunities import find_opportunities_real, find_opportunities_synthetic
from app.portfolio import simulate_portfolio_real, simulate_portfolio_synthetic
from app.ranking import rank_real_symbols, rank_synthetic_profiles
from app.recommend.engine import recommend
from app.screener import screen_real_symbols, screen_synthetic
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
    commission_bps: float | None = None,
    allow_short: bool = True,
    with_earnings: bool = False,
    with_news: bool = False,
) -> dict:
    try:
        df = get_ohlcv(symbol, period=period, interval=interval)
    except DataUnavailableError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    result = recommend(
        df,
        symbol=symbol,
        initial_capital=initial_capital,
        commission_bps=commission_bps,
        allow_short=allow_short,
    )
    if with_earnings:
        result = apply_earnings_overlay(result, symbol)
    if with_news:
        result = apply_news_overlay(result, symbol)
    return result


@app.get("/earnings/{symbol}")
def get_earnings(symbol: str) -> dict:
    """Historical EPS surprise track record + upcoming earnings date for a
    symbol (Finnhub). Requires FINNHUB_API_KEY to be configured server-side."""
    try:
        return earnings_report(symbol)
    except FinnhubUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/news/{symbol}")
def get_news(symbol: str) -> dict:
    """Recent news-sentiment summary for a symbol (Alpha Vantage). Requires
    ALPHAVANTAGE_API_KEY to be configured server-side."""
    try:
        return news_report(symbol)
    except AlphaVantageUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


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


@app.post("/rank")
def post_rank(request: RankRequest) -> dict:
    kwargs = dict(
        allow_short=request.allow_short,
        initial_capital=request.initial_capital,
        commission_bps=request.commission_bps,
    )
    try:
        if request.synthetic:
            return rank_synthetic_profiles(seed=request.seed, **kwargs)
        if not request.symbols:
            raise HTTPException(status_code=400, detail="symbols es obligatorio salvo que synthetic=true")
        return rank_real_symbols(
            request.symbols,
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


@app.post("/screen")
def post_screen(request: ScreenRequest) -> dict:
    try:
        if request.synthetic:
            return screen_synthetic(seed=request.seed, top_n=request.top_n)
        return screen_real_symbols(
            request.symbols,
            period=request.period,
            interval=request.interval,
            top_n=request.top_n,
        )
    except DataUnavailableError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/opportunities")
def post_opportunities(request: OpportunitiesRequest) -> dict:
    kwargs = dict(
        initial_capital=request.initial_capital,
        commission_bps=request.commission_bps,
        allow_short=request.allow_short,
        include_earnings=request.with_earnings,
        include_news=request.with_news,
        top_n=request.top_n,
    )
    try:
        if request.synthetic:
            return find_opportunities_synthetic(seed=request.seed, **kwargs)
        return find_opportunities_real(
            request.symbols,
            period=request.period,
            interval=request.interval,
            **kwargs,
        )
    except DataUnavailableError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/simulate-portfolio")
def post_simulate_portfolio(request: PortfolioSimulateRequest) -> dict:
    kwargs = dict(
        end_date=request.end_date,
        portfolio_size=request.portfolio_size,
        initial_capital=request.initial_capital,
        commission_bps=request.commission_bps,
        allow_short=request.allow_short,
        step=request.step,
        min_confidence_pct=request.min_confidence_pct,
        adaptive_learning=request.adaptive_learning,
        include_earnings=request.with_earnings,
        include_news=request.with_news,
        risk_parity_sizing=request.risk_parity_sizing,
        stop_loss_pct=request.stop_loss_pct,
        short_confidence_premium=request.short_confidence_premium,
        risk_regime_sizing=request.risk_regime_sizing,
        rebalance_months=request.rebalance_months,
    )
    if request.max_per_asset_class is not None:
        # Omit otherwise so each path's own smart default applies (2 for
        # real symbols; disabled for synthetic labels — see
        # simulate_portfolio_synthetic).
        kwargs["max_per_asset_class"] = request.max_per_asset_class
    try:
        if request.synthetic:
            return simulate_portfolio_synthetic(start_date=request.start_date, seed=request.seed, **kwargs)
        return simulate_portfolio_real(
            request.start_date,
            symbols=request.symbols,
            period=request.period,
            interval=request.interval,
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
