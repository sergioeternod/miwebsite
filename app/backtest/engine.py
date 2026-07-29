"""Vectorized long-only backtester.

Convention: a strategy's `position` at the close of bar i is entered at that
same close and held into bar i+1 (i.e. returns are computed with
`position.shift(1)`), which avoids look-ahead bias — you can only act on a
signal after you have seen it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from app.backtest.metrics import compute_metrics
from app.strategies.base import Strategy


@dataclass
class BacktestResult:
    symbol: str
    strategy: str
    metrics: dict
    trades: list[dict] = field(default_factory=list)
    equity_curve: pd.Series = field(default_factory=pd.Series)


def extract_trades(enriched: pd.DataFrame, commission_bps: float = 0.0) -> list[dict]:
    position = enriched["position"]
    close = enriched["Close"]
    commission_rate = commission_bps / 10000

    trades = []
    entry_idx = None
    for i in range(1, len(enriched)):
        prev_pos, curr_pos = position.iloc[i - 1], position.iloc[i]
        if prev_pos == 0 and curr_pos == 1:
            entry_idx = i
        elif prev_pos == 1 and curr_pos == 0 and entry_idx is not None:
            entry_price = float(close.iloc[entry_idx])
            exit_price = float(close.iloc[i])
            gross_return = exit_price / entry_price - 1
            net_return_pct = (gross_return - 2 * commission_rate) * 100
            trades.append(
                {
                    "entry_date": str(enriched.index[entry_idx]),
                    "exit_date": str(enriched.index[i]),
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "bars_held": i - entry_idx,
                    "return_pct": net_return_pct,
                }
            )
            entry_idx = None

    if entry_idx is not None:
        # Position still open at the end of the data window: mark-to-market
        # so it shows up as context, flagged as unrealized.
        entry_price = float(close.iloc[entry_idx])
        exit_price = float(close.iloc[-1])
        gross_return = exit_price / entry_price - 1
        trades.append(
            {
                "entry_date": str(enriched.index[entry_idx]),
                "exit_date": str(enriched.index[-1]),
                "entry_price": entry_price,
                "exit_price": exit_price,
                "bars_held": len(enriched) - 1 - entry_idx,
                "return_pct": (gross_return - commission_rate) * 100,
                "open": True,
            }
        )

    return trades


def run_backtest(
    df: pd.DataFrame,
    strategy: Strategy,
    symbol: str = "",
    initial_capital: float = 10_000.0,
    commission_bps: float = 5.0,
) -> BacktestResult:
    """Run `strategy` over historical OHLCV `df` and report performance."""
    if len(df) < 5:
        raise ValueError("Se necesitan al menos 5 barras de datos históricos para backtestear.")

    enriched = strategy.run(df)

    daily_returns = enriched["Close"].pct_change().fillna(0)
    position_shifted = enriched["position"].shift(1).fillna(0)
    trade_changes = enriched["position"].diff().abs().fillna(0)
    commission_rate = commission_bps / 10000

    strategy_returns = position_shifted * daily_returns - trade_changes * commission_rate
    equity_curve = initial_capital * (1 + strategy_returns).cumprod()

    trades = extract_trades(enriched, commission_bps)
    metrics = compute_metrics(equity_curve, trades, strategy_returns)

    return BacktestResult(
        symbol=symbol,
        strategy=strategy.name,
        metrics=metrics,
        trades=trades,
        equity_curve=equity_curve,
    )


def compare_strategies(
    df: pd.DataFrame,
    strategies: list[Strategy],
    symbol: str = "",
    initial_capital: float = 10_000.0,
    commission_bps: float = 5.0,
) -> list[BacktestResult]:
    """Run every strategy and rank by average profit per trade (descending) —
    the metric that best answers "mayor capacidad de ganancia por transacción"."""
    results = [
        run_backtest(df, s, symbol=symbol, initial_capital=initial_capital, commission_bps=commission_bps)
        for s in strategies
    ]
    return sorted(results, key=lambda r: r.metrics["avg_profit_per_trade_pct"], reverse=True)
