"""Simulator: replay a strategy (or all of them) over historical data —
either real market data or a synthetic scenario, optionally windowed to a
specific date range — and produce a full report (metrics, trade log, equity
curve, price series) suitable for printing or for rendering as a chart.
"""

from __future__ import annotations

import pandas as pd

from app.backtest.engine import compare_strategies, run_backtest
from app.config import default_commission_bps
from app.data.providers import get_ohlcv, filter_date_range
from app.data.synthetic import generate_ohlcv, regimes_for_range
from app.strategies import all_strategies, build_strategy


def simulate(
    df: pd.DataFrame,
    strategy_name: str | None = None,
    symbol: str = "",
    initial_capital: float = 10_000.0,
    commission_bps: float | None = None,
    allow_short: bool = True,
    regime_dates: list[tuple[str, str, str]] | None = None,
) -> dict:
    """Run one strategy (`strategy_name`) or all of them (None, ranked by
    average profit per trade) over historical `df` and return a full report.

    `commission_bps=None` resolves to a realistic default for `symbol`'s
    instrument type (see `app.config.DEFAULT_COMMISSION_BPS`); the resolved
    value is echoed back in the report so it's clear what was actually used.

    `regime_dates` (from a synthetic scenario) are date-based, so they are
    remapped to `df`'s actual positions here — this works whether `df` is
    the full generated series or a date-sliced window of it."""
    if len(df) < 5:
        raise ValueError("Se necesitan al menos 5 barras de datos en el rango seleccionado.")
    if commission_bps is None:
        commission_bps = default_commission_bps(symbol)

    if strategy_name:
        strategies = [build_strategy(strategy_name, allow_short=allow_short)]
        results = [
            run_backtest(
                df,
                strategies[0],
                symbol=symbol,
                initial_capital=initial_capital,
                commission_bps=commission_bps,
            )
        ]
    else:
        results = compare_strategies(
            df,
            all_strategies(allow_short=allow_short),
            symbol=symbol,
            initial_capital=initial_capital,
            commission_bps=commission_bps,
        )

    price_series = [
        {"date": str(idx), "close": round(float(close), 4)}
        for idx, close in zip(df.index, df["Close"])
    ]

    return {
        "symbol": symbol,
        "period_start": str(df.index[0]),
        "period_end": str(df.index[-1]),
        "num_bars": len(df),
        "initial_capital": initial_capital,
        "commission_bps": commission_bps,
        "allow_short": allow_short,
        "price_series": price_series,
        "regimes": regimes_for_range(df, regime_dates) if regime_dates else [],
        "results": [
            {
                "strategy": r.strategy,
                "metrics": r.metrics,
                "trades": r.trades,
                "equity_curve": [round(float(v), 4) for v in r.equity_curve.tolist()],
                "final_equity": round(float(r.equity_curve.iloc[-1]), 2) if len(r.equity_curve) else initial_capital,
            }
            for r in results
        ],
    }


def simulate_symbol(
    symbol: str,
    strategy_name: str | None = None,
    period: str = "2y",
    interval: str = "1d",
    start_date: str | None = None,
    end_date: str | None = None,
    initial_capital: float = 10_000.0,
    commission_bps: float | None = None,
    allow_short: bool = True,
) -> dict:
    """Simulate on real historical data for `symbol` (any Yahoo Finance
    ticker). If `start_date`/`end_date` (ISO, e.g. "2023-06-01") are given,
    they take precedence over `period` and fetch that exact window."""
    df = get_ohlcv(symbol, period=period, interval=interval, start=start_date, end=end_date)
    return simulate(
        df,
        strategy_name=strategy_name,
        symbol=symbol,
        initial_capital=initial_capital,
        commission_bps=commission_bps,
        allow_short=allow_short,
    )


def simulate_synthetic(
    strategy_name: str | None = None,
    regimes: list[dict] | None = None,
    symbol: str = "SYNTH",
    seed: int = 42,
    start_date: str | None = None,
    end_date: str | None = None,
    initial_capital: float = 10_000.0,
    commission_bps: float | None = None,
    allow_short: bool = True,
) -> dict:
    """Simulate on a generated synthetic scenario — no network required.
    Useful for demos, offline testing, or environments without market data
    access. `start_date`/`end_date` window the generated scenario down to a
    sub-range (e.g. just the "caída fuerte" stretch)."""
    df = generate_ohlcv(regimes=regimes, seed=seed)
    regime_dates = df.attrs.get("regimes", [])
    if start_date or end_date:
        df = filter_date_range(df, start_date, end_date)
    return simulate(
        df,
        strategy_name=strategy_name,
        symbol=symbol,
        initial_capital=initial_capital,
        commission_bps=commission_bps,
        allow_short=allow_short,
        regime_dates=regime_dates,
    )
