"""Combines the three validation analyses (out-of-sample split, per-trade
directional accuracy, walk-forward recommendation accuracy) into a single
report for a given historical dataset — real or synthetic.
"""

from __future__ import annotations

import pandas as pd

from app.data.providers import filter_date_range, get_ohlcv
from app.data.synthetic import generate_ohlcv, regimes_for_range
from app.strategies import Strategy, all_strategies
from app.validation.out_of_sample import out_of_sample_comparison
from app.validation.recommendation_accuracy import walk_forward_recommendation_accuracy
from app.validation.trade_accuracy import compare_directional_accuracy


def build_validation_report(
    df: pd.DataFrame,
    symbol: str = "",
    strategies: list[Strategy] | None = None,
    split_ratio: float = 0.5,
    horizon: int = 10,
    step: int = 10,
    warmup: int = 110,
    allow_short: bool = True,
    initial_capital: float = 10_000.0,
    commission_bps: float = 5.0,
    regime_dates: list[tuple[str, str, str]] | None = None,
) -> dict:
    if len(df) < warmup + horizon + 1:
        raise ValueError(
            f"Se necesitan al menos {warmup + horizon + 1} barras para validar "
            f"(warmup={warmup} + horizon={horizon}); hay {len(df)}."
        )

    strategies = strategies or all_strategies(allow_short=allow_short)

    price_series = [
        {"date": str(idx), "close": round(float(close), 4)} for idx, close in zip(df.index, df["Close"])
    ]

    return {
        "symbol": symbol,
        "period_start": str(df.index[0]),
        "period_end": str(df.index[-1]),
        "num_bars": len(df),
        "price_series": price_series,
        "regimes": regimes_for_range(df, regime_dates) if regime_dates else [],
        "out_of_sample": out_of_sample_comparison(
            df,
            strategies,
            split_ratio=split_ratio,
            symbol=symbol,
            initial_capital=initial_capital,
            commission_bps=commission_bps,
        ),
        "directional_accuracy": compare_directional_accuracy(
            df, strategies, symbol=symbol, initial_capital=initial_capital, commission_bps=commission_bps
        ),
        "recommendation_walk_forward": walk_forward_recommendation_accuracy(
            df,
            symbol=symbol,
            horizon=horizon,
            step=step,
            warmup=warmup,
            allow_short=allow_short,
            initial_capital=initial_capital,
            commission_bps=commission_bps,
        ),
    }


def validate_symbol(
    symbol: str,
    period: str = "2y",
    interval: str = "1d",
    start_date: str | None = None,
    end_date: str | None = None,
    **kwargs,
) -> dict:
    df = get_ohlcv(symbol, period=period, interval=interval, start=start_date, end=end_date)
    return build_validation_report(df, symbol=symbol, **kwargs)


def validate_synthetic(
    regimes: list[dict] | None = None,
    symbol: str = "SYNTH",
    seed: int = 42,
    start_date: str | None = None,
    end_date: str | None = None,
    **kwargs,
) -> dict:
    df = generate_ohlcv(regimes=regimes, seed=seed)
    regime_dates = df.attrs.get("regimes", [])
    if start_date or end_date:
        df = filter_date_range(df, start_date, end_date)
    return build_validation_report(df, symbol=symbol, regime_dates=regime_dates, **kwargs)
