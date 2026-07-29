"""Out-of-sample validation: run one continuous backtest, then split it into
an "expectation" period (A, earlier) and a "reality" period (B, later) to see
whether a strategy's performance in A predicted how it actually did in B.

This is a single continuous backtest split after the fact — not two separate
backtests — so indicators in period B still benefit from the same warm-up
they'd have in live trading (nothing about period B is recomputed in
isolation), while B's equity curve is rebased to the same starting capital as
A so the two periods' metrics are directly comparable regardless of how A
performed.
"""

from __future__ import annotations

import pandas as pd

from app.backtest.engine import run_backtest
from app.backtest.metrics import compute_metrics
from app.strategies.base import Strategy


def split_backtest_periods(
    df: pd.DataFrame,
    strategy: Strategy,
    split_ratio: float = 0.5,
    symbol: str = "",
    initial_capital: float = 10_000.0,
    commission_bps: float | None = None,
) -> dict:
    if not 0 < split_ratio < 1:
        raise ValueError("split_ratio debe estar entre 0 y 1")

    result = run_backtest(
        df, strategy, symbol=symbol, initial_capital=initial_capital, commission_bps=commission_bps
    )

    n = len(df)
    split_idx = int(n * split_ratio)
    split_idx = max(1, min(split_idx, n - 1))
    split_date = str(df.index[split_idx])

    equity = result.equity_curve
    equity_a = equity.iloc[: split_idx + 1]
    equity_b_raw = equity.iloc[split_idx:]
    rebase_factor = initial_capital / equity_b_raw.iloc[0]
    equity_b = equity_b_raw * rebase_factor

    returns_a = equity_a.pct_change().fillna(0)
    returns_b = equity_b.pct_change().fillna(0)

    # Trades are attributed to a period by their entry date. A trade that
    # opened in A and closed in B is counted entirely in A — its dollar
    # total_pnl_amount for B is therefore an approximation, not an exact
    # reconciliation against B's own equity delta, whenever such a straddling
    # trade exists (rare, but possible near the split date).
    trades_a = [t for t in result.trades if t["entry_date"] < split_date]
    # Dollar pnl_amount must be rescaled by the same factor as the equity
    # curve above — otherwise period B's dollar figures would still reflect
    # whatever capital period A happened to end with, defeating the point of
    # rebasing B to start fresh at initial_capital.
    trades_b = [
        {**t, "pnl_amount": round(t["pnl_amount"] * rebase_factor, 2)}
        for t in result.trades
        if t["entry_date"] >= split_date
    ]

    metrics_a = compute_metrics(equity_a, trades_a, returns_a)
    metrics_b = compute_metrics(equity_b, trades_b, returns_b)

    return {
        "strategy": strategy.name,
        "split_date": split_date,
        "period_a": {
            "label": "expectativa",
            "start": str(df.index[0]),
            "end": split_date,
            "metrics": metrics_a,
        },
        "period_b": {
            "label": "realidad",
            "start": split_date,
            "end": str(df.index[-1]),
            "metrics": metrics_b,
        },
        "consistency": {
            "profitability_sign_matches": (metrics_a["avg_profit_per_trade_pct"] > 0)
            == (metrics_b["avg_profit_per_trade_pct"] > 0),
            "avg_profit_per_trade_gap_pct": round(
                metrics_b["avg_profit_per_trade_pct"] - metrics_a["avg_profit_per_trade_pct"], 2
            ),
            "win_rate_gap_pct_points": round(metrics_b["win_rate_pct"] - metrics_a["win_rate_pct"], 2),
        },
    }


def out_of_sample_comparison(
    df: pd.DataFrame,
    strategies: list[Strategy],
    split_ratio: float = 0.5,
    symbol: str = "",
    initial_capital: float = 10_000.0,
    commission_bps: float | None = None,
) -> list[dict]:
    """Run `split_backtest_periods` for every strategy."""
    return [
        split_backtest_periods(
            df, s, split_ratio=split_ratio, symbol=symbol, initial_capital=initial_capital, commission_bps=commission_bps
        )
        for s in strategies
    ]
