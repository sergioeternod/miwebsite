"""Ensemble recommendation engine: runs every strategy on the latest data and
combines them into one BUY/SELL/HOLD call, weighted by each strategy's own
historical performance on that specific instrument.

This is a decision-support tool based on technical indicators and historical
backtests — not financial advice, and it does not account for execution
costs beyond a flat commission estimate. `recommend_for_symbol` can
optionally layer on two independent overlays that nudge confidence without
changing the technical BUY/SELL/HOLD call itself: an earnings-surprise-
history overlay (`app.fundamentals.earnings`, confidence adjusts when a
report is due soon) and a news-sentiment overlay
(`app.fundamentals.news_sentiment`, confidence adjusts based on recent,
sufficiently-relevant news tone).

The ensemble also tilts each strategy's vote by how well its *family*
(trend-following vs. mean-reversion) fits the market's current trend
strength (ADX) — trend-followers reliably get chopped up in range-bound
markets and mean-reversion strategies get run over in strong trends, so a
static full-history weight can't see a regime shift that just happened.
This narrows that blind spot; it does not, and cannot, guarantee a winning
call every time.
"""

from __future__ import annotations

import pandas as pd

from app.backtest.engine import run_backtest
from app.data.providers import get_ohlcv
from app.fundamentals.earnings import apply_earnings_overlay
from app.fundamentals.news_sentiment import apply_news_overlay
from app.indicators.technical import adx
from app.strategies import Strategy, all_strategies

BULLISH_ACTIONS = {"BUY", "HOLD_LONG"}
BEARISH_ACTIONS = {"SELL_SHORT", "HOLD_SHORT"}
# SELL (closed a long to flat), COVER (closed a short to flat) and HOLD_CASH
# are treated as neutral: they mean "no active directional bet right now".

TREND_STRATEGIES = {"sma_crossover", "macd_crossover", "bollinger_breakout", "trend_confirmation"}
MEAN_REVERSION_STRATEGIES = {"rsi_reversion"}

ADX_WINDOW = 14
# ADX below ~15 reads as a range-bound/choppy market (favors mean reversion);
# above ~40 reads as a strong trend (favors trend-following). Blended
# smoothly between them instead of a hard cutoff, since regimes shift
# gradually, not in a single bar.
ADX_WEAK_TREND = 15.0
ADX_STRONG_TREND = 40.0


def _strategy_weight(avg_profit_per_trade_pct: float) -> float:
    """Strategies with a losing track record on this instrument still get a
    tiny floor weight (so they aren't silently erased from the vote and
    can't divide by zero), but strategies with a winning track record are
    weighted proportionally to how profitable their trades have historically
    been. The floor is deliberately small — a strategy losing -15%/trade and
    one losing -0.1%/trade are not equally untrustworthy, so flooring both
    up to the same value (as an earlier, larger floor did) would erase that
    distinction instead of preserving it."""
    return max(avg_profit_per_trade_pct, 0.01)


def _strategy_family(name: str) -> str:
    if any(name.startswith(prefix) for prefix in TREND_STRATEGIES):
        return "trend"
    if any(name.startswith(prefix) for prefix in MEAN_REVERSION_STRATEGIES):
        return "mean_reversion"
    return "trend"  # unrecognized strategy name: no regime opinion either way


def _regime_multiplier(family: str, current_adx: float) -> float:
    if pd.isna(current_adx):
        return 1.0  # not enough history for ADX yet — stay neutral
    trend_strength = min(max((current_adx - ADX_WEAK_TREND) / (ADX_STRONG_TREND - ADX_WEAK_TREND), 0.0), 1.0)
    trend_multiplier = 0.6 + 0.8 * trend_strength  # 0.6 (range-bound) .. 1.4 (strong trend)
    return trend_multiplier if family == "trend" else 2.0 - trend_multiplier


def recommend(
    df: pd.DataFrame,
    symbol: str = "",
    strategies: list[Strategy] | None = None,
    initial_capital: float = 10_000.0,
    commission_bps: float | None = None,
    allow_short: bool = True,
) -> dict:
    strategies = strategies or all_strategies(allow_short=allow_short)
    current_adx = float(adx(df, window=ADX_WINDOW).iloc[-1]) if len(df) >= ADX_WINDOW * 2 else float("nan")

    per_strategy = []
    action_score = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0}
    total_weight = 0.0

    for strat in strategies:
        signal = strat.latest_signal(df)
        backtest = run_backtest(
            df, strat, symbol=symbol, initial_capital=initial_capital, commission_bps=commission_bps
        )
        family = _strategy_family(strat.name)
        regime_multiplier = _regime_multiplier(family, current_adx)
        weight = _strategy_weight(backtest.metrics["avg_profit_per_trade_pct"]) * regime_multiplier
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
                "regime_multiplier": round(regime_multiplier, 2),
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
        "market_regime": {
            "adx": round(current_adx, 1) if not pd.isna(current_adx) else None,
            "reading": (
                None
                if pd.isna(current_adx)
                else "tendencia fuerte" if current_adx >= ADX_STRONG_TREND
                else "rango / sin tendencia clara" if current_adx <= ADX_WEAK_TREND
                else "transición"
            ),
        },
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
    commission_bps: float | None = None,
    allow_short: bool = True,
    include_earnings: bool = False,
    finnhub_api_key: str | None = None,
    include_news: bool = False,
    alphavantage_api_key: str | None = None,
) -> dict:
    df = get_ohlcv(symbol, period=period, interval=interval)
    result = recommend(
        df,
        symbol=symbol,
        strategies=strategies,
        initial_capital=initial_capital,
        commission_bps=commission_bps,
        allow_short=allow_short,
    )
    if include_earnings:
        result = apply_earnings_overlay(result, symbol, api_key=finnhub_api_key)
    if include_news:
        result = apply_news_overlay(result, symbol, api_key=alphavantage_api_key)
    return result
