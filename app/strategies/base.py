"""Base strategy interface shared by all concrete strategies.

Strategies support long AND short positions: each bar has a position of
1 (long), -1 (short) or 0 (flat/cash). A strategy can be restricted to
long-only via `allow_short=False` (e.g. for spot crypto/forex accounts that
cannot short without margin, or when the user prefers not to bet on declines).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


def stateful_positions(
    long_entry: pd.Series,
    long_exit: pd.Series,
    short_entry: pd.Series | None = None,
    short_exit: pd.Series | None = None,
    allow_short: bool = True,
) -> pd.Series:
    """Turn entry/exit boolean signals into a -1/0/1 position series.

    Starts flat. Goes long on `long_entry`, stays long until `long_exit`.
    If `allow_short` and short signals are provided, goes short on
    `short_entry` and stays short until `short_exit`. A short signal that
    fires while long (or a long signal while short) immediately flips the
    position — closing the old side and opening the new one on that same
    bar — rather than requiring a trip back through flat first.
    Rows where a signal is NaN (indicator warm-up period) are treated as False.
    """
    index = long_entry.index
    n = len(index)
    long_entry_v = long_entry.fillna(False).to_numpy()
    long_exit_v = long_exit.fillna(False).to_numpy()
    if allow_short and short_entry is not None and short_exit is not None:
        short_entry_v = short_entry.fillna(False).to_numpy()
        short_exit_v = short_exit.fillna(False).to_numpy()
    else:
        short_entry_v = [False] * n
        short_exit_v = [False] * n

    positions = []
    position = 0
    for i in range(n):
        if position == 0:
            if long_entry_v[i]:
                position = 1
            elif short_entry_v[i]:
                position = -1
        elif position == 1:
            if long_exit_v[i]:
                position = -1 if short_entry_v[i] else 0
        elif position == -1:
            if short_exit_v[i]:
                position = 1 if long_entry_v[i] else 0
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

    def __init__(self, allow_short: bool = True):
        self.allow_short = allow_short

    @abstractmethod
    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Return a copy of df with the indicator columns this strategy needs."""

    @abstractmethod
    def generate_signals(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        """Return boolean Series for 'long_entry', 'long_exit', 'short_entry', 'short_exit'."""

    def generate_positions(self, df: pd.DataFrame) -> pd.Series:
        signals = self.generate_signals(df)
        return stateful_positions(
            signals["long_entry"],
            signals["long_exit"],
            signals.get("short_entry"),
            signals.get("short_exit"),
            allow_short=self.allow_short,
        )

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

        if position_now == 1 and position_prev != 1:
            action = "BUY"
        elif position_now == -1 and position_prev != -1:
            action = "SELL_SHORT"
        elif position_now == 0 and position_prev == 1:
            action = "SELL"
        elif position_now == 0 and position_prev == -1:
            action = "COVER"
        elif position_now == 1:
            action = "HOLD_LONG"
        elif position_now == -1:
            action = "HOLD_SHORT"
        else:
            action = "HOLD_CASH"

        return {
            "strategy": self.name,
            "action": action,
            "as_of": str(enriched.index[-1]),
            "details": self.explain(enriched),
        }
