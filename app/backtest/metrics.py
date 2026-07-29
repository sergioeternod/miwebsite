"""Performance metrics computed from a backtest's equity curve and trade list."""

from __future__ import annotations

import pandas as pd


def compute_metrics(
    equity_curve: pd.Series,
    trades: list[dict],
    strategy_returns: pd.Series,
    periods_per_year: int = 252,
) -> dict:
    total_return_pct = (equity_curve.iloc[-1] / equity_curve.iloc[0] - 1) * 100

    years = len(equity_curve) / periods_per_year
    if years > 0 and equity_curve.iloc[0] > 0 and equity_curve.iloc[-1] > 0:
        cagr_pct = ((equity_curve.iloc[-1] / equity_curve.iloc[0]) ** (1 / years) - 1) * 100
    else:
        cagr_pct = 0.0

    running_max = equity_curve.cummax()
    drawdown = equity_curve / running_max - 1
    max_drawdown_pct = drawdown.min() * 100

    sharpe_ratio = 0.0
    if strategy_returns.std(ddof=0) > 0:
        sharpe_ratio = (strategy_returns.mean() / strategy_returns.std(ddof=0)) * (periods_per_year ** 0.5)

    n_trades = len(trades)
    wins = [t for t in trades if t["return_pct"] > 0]
    losses = [t for t in trades if t["return_pct"] <= 0]

    win_rate_pct = (len(wins) / n_trades * 100) if n_trades else 0.0
    avg_profit_per_trade_pct = (sum(t["return_pct"] for t in trades) / n_trades) if n_trades else 0.0
    gross_profit = sum(t["return_pct"] for t in wins)
    gross_loss = abs(sum(t["return_pct"] for t in losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None

    has_amounts = n_trades > 0 and all("pnl_amount" in t for t in trades)
    total_pnl_amount = round(sum(t["pnl_amount"] for t in trades), 2) if has_amounts else None
    avg_profit_per_trade_amount = round(total_pnl_amount / n_trades, 2) if has_amounts and n_trades else None
    best_trade_amount = round(max((t["pnl_amount"] for t in trades), default=0.0), 2) if has_amounts else None
    worst_trade_amount = round(min((t["pnl_amount"] for t in trades), default=0.0), 2) if has_amounts else None

    return {
        "total_return_pct": round(total_return_pct, 2),
        "cagr_pct": round(cagr_pct, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "sharpe_ratio": round(float(sharpe_ratio), 2),
        "num_trades": n_trades,
        "win_rate_pct": round(win_rate_pct, 2),
        "avg_profit_per_trade_pct": round(avg_profit_per_trade_pct, 2),
        "best_trade_pct": round(max((t["return_pct"] for t in trades), default=0.0), 2),
        "worst_trade_pct": round(min((t["return_pct"] for t in trades), default=0.0), 2),
        "avg_win_pct": round((gross_profit / len(wins)) if wins else 0.0, 2),
        "avg_loss_pct": round(-(gross_loss / len(losses)) if losses else 0.0, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor is not None else None,
        "total_pnl_amount": total_pnl_amount,
        "avg_profit_per_trade_amount": avg_profit_per_trade_amount,
        "best_trade_amount": best_trade_amount,
        "worst_trade_amount": worst_trade_amount,
    }
