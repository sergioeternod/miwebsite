"""Vectorized long/short backtester.

Convention: a strategy's `position` at the close of bar i is entered at that
same close and held into bar i+1 (i.e. returns are computed with
`position.shift(1)`), which avoids look-ahead bias — you can only act on a
signal after you have seen it. `position` is -1 (short), 0 (flat) or 1 (long).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from app.backtest.metrics import compute_metrics
from app.config import default_commission_bps
from app.strategies.base import Strategy


@dataclass
class BacktestResult:
    symbol: str
    strategy: str
    metrics: dict
    trades: list[dict] = field(default_factory=list)
    equity_curve: pd.Series = field(default_factory=pd.Series)


def extract_trades(
    enriched: pd.DataFrame,
    commission_bps: float = 0.0,
    equity_curve: pd.Series | None = None,
    initial_capital: float = 10_000.0,
) -> list[dict]:
    """Turn a -1/0/1 position series into a list of closed (and one possibly
    open) trades. A direct flip (long->short or short->long on the same bar)
    closes the old trade and opens the new one at that bar's close.

    If `equity_curve` is given, each trade's `return_pct` and dollar
    `pnl_amount` are derived directly from it (equity_at_exit / equity_at_entry)
    instead of from the raw entry/exit price ratio. This matters for short
    trades held over multiple bars: the equity curve compounds daily
    percent-of-equity returns (rebalanced exposure), which is not the same
    number as a simple entry-vs-exit price ratio once there's day-to-day
    volatility during the trade (a well-known "compounding drag" effect) —
    deriving from the equity curve keeps every reported number (including
    dollar P&L) exactly consistent with the equity curve everything else is
    built on, rather than silently disagreeing with it. Each trade's entry
    base is carried forward from the previous trade's own exit equity (not
    read off the equity curve by index), since a flipped position closes the
    old trade and opens the new one on the very same bar — indexing off that
    bar directly would double back into the old trade's own return. Without
    an `equity_curve` (e.g. a caller inspecting positions in isolation),
    falls back to the plain price-ratio calculation and `initial_capital` as
    the notional base."""
    position = enriched["position"]
    close = enriched["Close"]
    commission_rate = commission_bps / 10000

    trades: list[dict] = []
    open_trade: dict | None = None
    equity_base = initial_capital  # this trade's starting capital = the previous trade's ending capital

    def _close(exit_idx: int, mark_open: bool = False) -> None:
        nonlocal open_trade, equity_base
        direction = open_trade["direction"]
        entry_idx = open_trade["entry_idx"]
        entry_price = open_trade["entry_price"]
        exit_price = float(close.iloc[exit_idx])

        if equity_curve is not None:
            equity_at_entry = equity_base
            equity_at_exit = float(equity_curve.iloc[exit_idx])
            net_return_pct = (equity_at_exit / equity_at_entry - 1) * 100
            equity_base = equity_at_exit
        else:
            gross_return = (
                exit_price / entry_price - 1 if direction == 1 else entry_price / exit_price - 1
            )
            commission_legs = 1 if mark_open else 2
            net_return_pct = (gross_return - commission_legs * commission_rate) * 100
            equity_at_entry = initial_capital

        trade = {
            "direction": "long" if direction == 1 else "short",
            "entry_date": str(enriched.index[entry_idx]),
            "exit_date": str(enriched.index[exit_idx]),
            "entry_price": entry_price,
            "exit_price": exit_price,
            "bars_held": exit_idx - entry_idx,
            "return_pct": net_return_pct,
            "pnl_amount": round(equity_at_entry * net_return_pct / 100, 2),
            "equity_at_entry": round(equity_at_entry, 2),
        }
        if mark_open:
            trade["open"] = True
        trades.append(trade)
        open_trade = None

    for i in range(len(enriched)):
        curr_pos = int(position.iloc[i])
        prev_pos = int(position.iloc[i - 1]) if i > 0 else 0
        if curr_pos == prev_pos:
            continue
        if open_trade is not None:
            _close(i)
        if curr_pos != 0:
            open_trade = {"direction": curr_pos, "entry_idx": i, "entry_price": float(close.iloc[i])}

    if open_trade is not None:
        # Position still open at the end of the data window: mark-to-market
        # so it shows up as context, flagged as unrealized.
        _close(len(enriched) - 1, mark_open=True)

    return trades


def run_backtest(
    df: pd.DataFrame,
    strategy: Strategy,
    symbol: str = "",
    initial_capital: float = 10_000.0,
    commission_bps: float | None = None,
) -> BacktestResult:
    """Run `strategy` over historical OHLCV `df` and report performance.

    `commission_bps=None` (the default) resolves to a realistic one-way cost
    for `symbol`'s instrument type (see `app.config.DEFAULT_COMMISSION_BPS`)
    instead of one flat guess for every asset class."""
    if len(df) < 5:
        raise ValueError("Se necesitan al menos 5 barras de datos históricos para backtestear.")
    if commission_bps is None:
        commission_bps = default_commission_bps(symbol)

    enriched = strategy.run(df)

    daily_returns = enriched["Close"].pct_change().fillna(0)
    position_shifted = enriched["position"].shift(1).fillna(0)
    trade_changes = enriched["position"].diff().abs().fillna(0)
    commission_rate = commission_bps / 10000

    strategy_returns = position_shifted * daily_returns - trade_changes * commission_rate
    equity_curve = initial_capital * (1 + strategy_returns).cumprod()

    trades = extract_trades(enriched, commission_bps, equity_curve=equity_curve, initial_capital=initial_capital)
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
    commission_bps: float | None = None,
) -> list[BacktestResult]:
    """Run every strategy and rank by average profit per trade (descending) —
    the metric that best answers "mayor capacidad de ganancia por transacción"."""
    results = [
        run_backtest(df, s, symbol=symbol, initial_capital=initial_capital, commission_bps=commission_bps)
        for s in strategies
    ]
    return sorted(results, key=lambda r: r.metrics["avg_profit_per_trade_pct"], reverse=True)
