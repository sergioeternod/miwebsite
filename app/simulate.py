"""Simulator: replay a strategy (or all of them) over historical data —
either real market data or a synthetic scenario — and produce a full report
(metrics, trade log, equity curve, price series) suitable for printing or
for rendering as a chart.
"""

from __future__ import annotations

import pandas as pd

from app.backtest.engine import compare_strategies, run_backtest
from app.data.providers import get_ohlcv
from app.data.synthetic import generate_ohlcv
from app.strategies import all_strategies, build_strategy


def simulate(
    df: pd.DataFrame,
    strategy_name: str | None = None,
    symbol: str = "",
    initial_capital: float = 10_000.0,
    commission_bps: float = 5.0,
    allow_short: bool = True,
) -> dict:
    """Run one strategy (`strategy_name`) or all of them (None, ranked by
    average profit per trade) over historical `df` and return a full report."""
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
        "regimes": df.attrs.get("regimes", []),
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
    initial_capital: float = 10_000.0,
    commission_bps: float = 5.0,
    allow_short: bool = True,
) -> dict:
    """Simulate on real historical data for `symbol` (any Yahoo Finance ticker)."""
    df = get_ohlcv(symbol, period=period, interval=interval)
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
    initial_capital: float = 10_000.0,
    commission_bps: float = 5.0,
    allow_short: bool = True,
) -> dict:
    """Simulate on a generated synthetic scenario — no network required.
    Useful for demos, offline testing, or environments without market data
    access."""
    df = generate_ohlcv(regimes=regimes, seed=seed)
    return simulate(
        df,
        strategy_name=strategy_name,
        symbol=symbol,
        initial_capital=initial_capital,
        commission_bps=commission_bps,
        allow_short=allow_short,
    )
