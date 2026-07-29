"""Synthetic OHLCV data generator.

Used to exercise the simulator/backtester without depending on network access
to a live market data provider (useful offline, in CI, or in network-locked
sandboxes), and to build demo scenarios that deliberately include bull, bear
and sideways stretches so both long and short logic gets exercised.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# A demo scenario with clearly alternating regimes: a strong uptrend, a
# correction, a sideways chop, a sharper sell-off and a recovery — enough
# for trend-following and mean-reversion strategies to take both long and
# short trades.
DEFAULT_DEMO_REGIMES = [
    {"name": "alza sostenida", "days": 90, "drift": 0.0025, "volatility": 0.012},
    {"name": "corrección", "days": 60, "drift": -0.0035, "volatility": 0.02},
    {"name": "lateral", "days": 50, "drift": 0.0002, "volatility": 0.008},
    {"name": "caída fuerte", "days": 45, "drift": -0.006, "volatility": 0.025},
    {"name": "recuperación", "days": 75, "drift": 0.003, "volatility": 0.015},
]


def generate_ohlcv(
    regimes: list[dict] | None = None,
    start_price: float = 100.0,
    start_date: str = "2023-01-01",
    seed: int = 42,
    high_low_noise: float = 0.01,
) -> pd.DataFrame:
    """Generate a synthetic daily OHLCV series made of consecutive regimes.

    Each regime is a dict with `days`, `drift` (mean daily return) and
    `volatility` (daily return std dev). Regime boundaries are stored in
    `df.attrs["regimes"]` as (name, start_idx, end_idx) for annotating charts.
    """
    regimes = regimes or DEFAULT_DEMO_REGIMES
    rng = np.random.default_rng(seed)

    closes = [start_price]
    regime_bounds = []
    for regime in regimes:
        days = regime["days"]
        start_idx = len(closes) - 1
        returns = rng.normal(regime.get("drift", 0.0), regime.get("volatility", 0.015), days)
        for r in returns:
            closes.append(closes[-1] * (1 + r))
        regime_bounds.append((regime["name"], start_idx, len(closes) - 1))

    close = pd.Series(closes[1:])
    open_ = pd.Series([start_price, *closes[1:-1]])
    n = len(close)

    bar_high = pd.concat([open_, close], axis=1).max(axis=1) * (1 + rng.uniform(0, high_low_noise, n))
    bar_low = pd.concat([open_, close], axis=1).min(axis=1) * (1 - rng.uniform(0, high_low_noise, n))
    volume = rng.integers(1_000, 5_000, n)

    df = pd.DataFrame(
        {
            "Open": open_.to_numpy(),
            "High": bar_high.to_numpy(),
            "Low": bar_low.to_numpy(),
            "Close": close.to_numpy(),
            "Volume": volume,
        }
    )
    df.index = pd.date_range(start_date, periods=n, freq="D")
    df.index.name = "Date"
    # Store regime boundaries as dates (not integer positions): positions only
    # make sense against this exact df, and become wrong the moment the
    # caller slices it down to a date range. `regimes_for_range` recomputes
    # positions against whatever (possibly sliced) df is actually plotted.
    df.attrs["regimes"] = [
        (name, str(df.index[min(start_idx, n - 1)].date()), str(df.index[min(end_idx, n - 1)].date()))
        for name, start_idx, end_idx in regime_bounds
    ]
    return df


def regimes_for_range(
    df: pd.DataFrame, regime_dates: list[tuple[str, str, str]]
) -> list[tuple[str, int, int]]:
    """Recompute integer (start_idx, end_idx) bounds for `regime_dates`
    against `df`'s actual index — which may be a date-sliced subset of the
    df the regimes were originally generated on. Regimes fully outside the
    window are dropped; partially-overlapping ones are clipped."""
    idx = df.index
    result = []
    for name, start_d, end_d in regime_dates:
        mask = (idx >= pd.Timestamp(start_d)) & (idx <= pd.Timestamp(end_d))
        positions = np.flatnonzero(mask)
        if len(positions) == 0:
            continue
        result.append((name, int(positions[0]), int(positions[-1])))
    return result
