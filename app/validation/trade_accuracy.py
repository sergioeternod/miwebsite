"""Per-trade directional accuracy: every trade a strategy takes is an implicit
bet on direction (long = "expects price to rise", short = "expects price to
fall"). This annotates each trade with that expectation and whether reality
(the realized return) matched it, then aggregates a hit rate — a more
granular, explicit view of the same information win_rate summarizes.
"""

from __future__ import annotations

import pandas as pd

from app.backtest.engine import run_backtest
from app.strategies.base import Strategy


def annotate_trade_hits(trades: list[dict]) -> list[dict]:
    annotated = []
    for t in trades:
        expected_direction = "sube" if t["direction"] == "long" else "baja"
        annotated.append({**t, "expected_direction": expected_direction, "hit": t["return_pct"] > 0})
    return annotated


def _hit_rate(trades: list[dict]) -> float | None:
    if not trades:
        return None
    return round(sum(1 for t in trades if t["hit"]) / len(trades) * 100, 2)


def directional_accuracy(trades: list[dict]) -> dict:
    annotated = annotate_trade_hits(trades)
    long_trades = [t for t in annotated if t["direction"] == "long"]
    short_trades = [t for t in annotated if t["direction"] == "short"]
    return {
        "num_trades": len(annotated),
        "hit_rate_pct": _hit_rate(annotated) or 0.0,
        "num_long": len(long_trades),
        "long_hit_rate_pct": _hit_rate(long_trades),
        "num_short": len(short_trades),
        "short_hit_rate_pct": _hit_rate(short_trades),
    }


def strategy_directional_accuracy(
    df: pd.DataFrame,
    strategy: Strategy,
    symbol: str = "",
    initial_capital: float = 10_000.0,
    commission_bps: float | None = None,
) -> dict:
    result = run_backtest(
        df, strategy, symbol=symbol, initial_capital=initial_capital, commission_bps=commission_bps
    )
    return {
        "strategy": strategy.name,
        "accuracy": directional_accuracy(result.trades),
        "trades": annotate_trade_hits(result.trades),
    }


def compare_directional_accuracy(
    df: pd.DataFrame,
    strategies: list[Strategy],
    symbol: str = "",
    initial_capital: float = 10_000.0,
    commission_bps: float | None = None,
) -> list[dict]:
    return [
        strategy_directional_accuracy(
            df, s, symbol=symbol, initial_capital=initial_capital, commission_bps=commission_bps
        )
        for s in strategies
    ]
