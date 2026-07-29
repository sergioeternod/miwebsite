"""Base strategy interface shared by all concrete strategies.

Strategies are long-only for this MVP (no short selling): each bar has a
position of 1 (long) or 0 (flat/cash). This keeps the backtester and the
recommendation engine simple while still covering trend-following and
mean-reversion styles across any instrument (stocks, crypto, forex, etc.).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


def stateful_positions(entry: pd.Series, exit_: pd.Series) -> pd.Series:
    """Turn entry/exit boolean signals into a 0/1 position series.

    Starts flat. Goes long on the first `entry`, stays long until the next
    `exit_`, then repeats. Rows where either signal is NaN (indicator warm-up
    period) are treated as False.
    """
    index = entry.index
    entry_values = entry.fillna(False).to_numpy()
    exit_values = exit_.fillna(False).to_numpy()
    positions = []
    position = 0
    for is_entry, is_exit in zip(entry_values, exit_values):
        if position == 0 and is_entry:
            position = 1
        elif position == 1 and is_exit:
            position = 0
        positions.append(position)
    return pd.Series(positions, index=index)


def _crosses_above(a: pd.Series, b: pd.Series) -> pd.Series:
    prev_a, prev_b = a.shift(1), b.shift(1)
    # Treat the first bar where both series become valid as an implicit
    # "was not yet above" state, so an indicator that starts already above
    # (a common case right after its warm-up window) still triggers an entry
    # instead of silently never firing a crossover.
    was_not_above = (prev_a <= prev_b) | prev_a.isna() | prev_b.isna()
    return (a > b) & was_not_above


def _crosses_below(a: pd.Series, b: pd.Series) -> pd.Series:
    prev_a, prev_b = a.shift(1), b.shift(1)
    was_not_below = (prev_a >= prev_b) | prev_a.isna() | prev_b.isna()
    return (a < b) & was_not_below


class Strategy(ABC):
    name: str = "base"

    @abstractmethod
    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return a copy of df with the indicator columns this strategy needs."""

    @abstractmethod
    def generate_positions(self, df: pd.DataFrame) -> pd.Series:
        """Return a 0/1 Series (index-aligned to df) with the desired position."""

    def explain(self, df: pd.DataFrame) -> dict:
        """Key indicator values for the last bar, used as recommendation reasoning."""
        return {}

    def run(self, df: pd.DataFrame) -> pd.DataFrame:
        enriched = self.add_indicators(df)
        enriched["position"] = self.generate_positions(enriched).to_numpy()
        return enriched

    def latest_signal(self, df: pd.DataFrame) -> dict:
        enriched = self.run(df)
        if len(enriched) < 2:
            raise ValueError("Se necesitan al menos 2 barras de datos para generar una señal.")
        last, prev = enriched.iloc[-1], enriched.iloc[-2]
        position_now, position_prev = int(last["position"]), int(prev["position"])

        if position_now == 1 and position_prev == 0:
            action = "BUY"
        elif position_now == 0 and position_prev == 1:
            action = "SELL"
        elif position_now == 1:
            action = "HOLD_LONG"
        else:
            action = "HOLD_CASH"

        return {
            "strategy": self.name,
            "action": action,
            "as_of": str(enriched.index[-1]),
            "details": self.explain(enriched),
        }
