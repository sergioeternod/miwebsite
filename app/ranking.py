"""Strategy × symbol ranking: runs every strategy against every symbol (real
tickers, or synthetic market-character profiles when there's no network) and
reports which symbol each strategy performs best on, and which strategy
performs best on each symbol.
"""

from __future__ import annotations

import pandas as pd

from app.backtest.engine import run_backtest
from app.data.providers import get_ohlcv
from app.data.synthetic import generate_ohlcv
from app.strategies import Strategy, all_strategies

# A handful of distinct market "characters" to stand in for real symbols when
# there's no network access. Real symbols behave like a mix of these over
# time; comparing strategies across these profiles shows the same thing a
# comparison across real tickers would: no strategy wins everywhere.
DEFAULT_SYMBOL_PROFILES = [
    {"label": "Tendencia alcista sostenida", "regimes": [{"name": "alza", "days": 260, "drift": 0.0012, "volatility": 0.012}]},
    {"label": "Tendencia bajista sostenida", "regimes": [{"name": "baja", "days": 260, "drift": -0.0012, "volatility": 0.014}]},
    {"label": "Lateral / rango", "regimes": [{"name": "lateral", "days": 260, "drift": 0.0000, "volatility": 0.010}]},
    {"label": "Alta volatilidad / whipsaw", "regimes": [{"name": "volátil", "days": 260, "drift": 0.0003, "volatility": 0.030}]},
    {
        "label": "Mixto (alza, corrección, lateral, caída, recuperación)",
        "regimes": [
            {"name": "alza sostenida", "days": 90, "drift": 0.0025, "volatility": 0.012},
            {"name": "corrección", "days": 60, "drift": -0.0035, "volatility": 0.02},
            {"name": "lateral", "days": 50, "drift": 0.0002, "volatility": 0.008},
            {"name": "caída fuerte", "days": 45, "drift": -0.006, "volatility": 0.025},
            {"name": "recuperación", "days": 75, "drift": 0.003, "volatility": 0.015},
        ],
    },
]


def build_symbol_strategy_matrix(
    dfs: dict[str, pd.DataFrame],
    strategies: list[Strategy] | None = None,
    allow_short: bool = True,
    initial_capital: float = 10_000.0,
    commission_bps: float = 5.0,
) -> dict:
    """Run every strategy on every {label: df} entry and rank the results
    both ways: best symbol per strategy, and best strategy per symbol."""
    strategies = strategies or all_strategies(allow_short=allow_short)

    matrix = []
    for label, df in dfs.items():
        for strategy in strategies:
            result = run_backtest(
                df, strategy, symbol=label, initial_capital=initial_capital, commission_bps=commission_bps
            )
            matrix.append({"symbol": label, "strategy": strategy.name, "metrics": result.metrics})

    def _best(rows: list[dict]) -> dict:
        best = max(rows, key=lambda r: r["metrics"]["avg_profit_per_trade_pct"])
        return {
            "avg_profit_per_trade_pct": best["metrics"]["avg_profit_per_trade_pct"],
            "total_return_pct": best["metrics"]["total_return_pct"],
            "total_pnl_amount": best["metrics"]["total_pnl_amount"],
            "num_trades": best["metrics"]["num_trades"],
        }

    best_symbol_per_strategy = {}
    for strategy in strategies:
        rows = [r for r in matrix if r["strategy"] == strategy.name]
        best_symbol_per_strategy[strategy.name] = {"symbol": max(rows, key=lambda r: r["metrics"]["avg_profit_per_trade_pct"])["symbol"], **_best(rows)}

    best_strategy_per_symbol = {}
    for label in dfs:
        rows = [r for r in matrix if r["symbol"] == label]
        best_strategy_per_symbol[label] = {"strategy": max(rows, key=lambda r: r["metrics"]["avg_profit_per_trade_pct"])["strategy"], **_best(rows)}

    return {
        "symbols": list(dfs.keys()),
        "strategies": [s.name for s in strategies],
        "matrix": matrix,
        "best_symbol_per_strategy": best_symbol_per_strategy,
        "best_strategy_per_symbol": best_strategy_per_symbol,
    }


def rank_real_symbols(
    symbols: list[str],
    strategies: list[Strategy] | None = None,
    period: str = "2y",
    interval: str = "1d",
    start_date: str | None = None,
    end_date: str | None = None,
    allow_short: bool = True,
    initial_capital: float = 10_000.0,
    commission_bps: float = 5.0,
) -> dict:
    """Rank real Yahoo Finance symbols by how each strategy performs on them."""
    if not symbols:
        raise ValueError("Se necesita al menos un símbolo.")
    dfs = {sym: get_ohlcv(sym, period=period, interval=interval, start=start_date, end=end_date) for sym in symbols}
    return build_symbol_strategy_matrix(
        dfs,
        strategies=strategies,
        allow_short=allow_short,
        initial_capital=initial_capital,
        commission_bps=commission_bps,
    )


def rank_synthetic_profiles(
    profiles: list[dict] | None = None,
    strategies: list[Strategy] | None = None,
    seed: int = 42,
    allow_short: bool = True,
    initial_capital: float = 10_000.0,
    commission_bps: float = 5.0,
) -> dict:
    """Rank synthetic market-character profiles (no network required) — a
    stand-in for "which symbols work best" when real tickers aren't reachable."""
    profiles = profiles or DEFAULT_SYMBOL_PROFILES
    dfs = {profile["label"]: generate_ohlcv(regimes=profile["regimes"], seed=seed) for profile in profiles}
    return build_symbol_strategy_matrix(
        dfs,
        strategies=strategies,
        allow_short=allow_short,
        initial_capital=initial_capital,
        commission_bps=commission_bps,
    )
