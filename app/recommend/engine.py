"""Ensemble recommendation engine: runs every strategy on the latest data and
combines them into one BUY/SELL/HOLD call, weighted by each strategy's own
historical performance on that specific instrument.

This is a decision-support tool based on technical indicators and historical
backtests — not financial advice, and it does not account for fundamentals,
news, or execution costs beyond a flat commission estimate.
"""

from __future__ import annotations

import pandas as pd

from app.backtest.engine import run_backtest
from app.data.providers import get_ohlcv
from app.strategies import Strategy, all_strategies

BULLISH_ACTIONS = {"BUY", "HOLD_LONG"}
BEARISH_ACTIONS = {"SELL"}


def _strategy_weight(avg_profit_per_trade_pct: float) -> float:
    """Strategies with a losing track record on this instrument still get a
    small floor weight (so they aren't silently erased from the vote), but
    strategies with a winning track record are weighted proportionally to
    how profitable their trades have historically been."""
    return max(avg_profit_per_trade_pct, 0.05)


def recommend(
    df: pd.DataFrame,
    symbol: str = "",
    strategies: list[Strategy] | None = None,
    initial_capital: float = 10_000.0,
    commission_bps: float = 5.0,
) -> dict:
    strategies = strategies or all_strategies()

    per_strategy = []
    action_score = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0}
    total_weight = 0.0

    for strat in strategies:
        signal = strat.latest_signal(df)
        backtest = run_backtest(
            df, strat, symbol=symbol, initial_capital=initial_capital, commission_bps=commission_bps
        )
        weight = _strategy_weight(backtest.metrics["avg_profit_per_trade_pct"])
        total_weight += weight

        if signal["action"] in BULLISH_ACTIONS:
            action_score["BUY"] += weight
        elif signal["action"] in BEARISH_ACTIONS:
            action_score["SELL"] += weight
        else:
            action_score["HOLD"] += weight

        per_strategy.append(
            {
                "strategy": strat.name,
                "signal": signal["action"],
                "details": signal["details"],
                "historical_avg_profit_per_trade_pct": backtest.metrics["avg_profit_per_trade_pct"],
                "historical_win_rate_pct": backtest.metrics["win_rate_pct"],
                "historical_num_trades": backtest.metrics["num_trades"],
            }
        )

    overall_action = max(action_score, key=action_score.get) if total_weight > 0 else "HOLD"
    confidence_pct = round((action_score[overall_action] / total_weight * 100), 1) if total_weight > 0 else 0.0

    best_by_profit_per_trade = max(
        per_strategy, key=lambda s: s["historical_avg_profit_per_trade_pct"]
    )

    return {
        "symbol": symbol,
        "as_of": str(df.index[-1]),
        "last_close": round(float(df["Close"].iloc[-1]), 4),
        "overall_action": overall_action,
        "confidence_pct": confidence_pct,
        "per_strategy": per_strategy,
        "best_historical_strategy": {
            "strategy": best_by_profit_per_trade["strategy"],
            "avg_profit_per_trade_pct": best_by_profit_per_trade["historical_avg_profit_per_trade_pct"],
        },
        "disclaimer": (
            "Esta recomendación se basa únicamente en indicadores técnicos y backtests "
            "históricos; no es asesoría financiera y no garantiza resultados futuros."
        ),
    }


def recommend_for_symbol(
    symbol: str,
    period: str = "2y",
    interval: str = "1d",
    strategies: list[Strategy] | None = None,
    initial_capital: float = 10_000.0,
    commission_bps: float = 5.0,
) -> dict:
    df = get_ohlcv(symbol, period=period, interval=interval)
    return recommend(
        df,
        symbol=symbol,
        strategies=strategies,
        initial_capital=initial_capital,
        commission_bps=commission_bps,
    )
