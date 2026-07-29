from __future__ import annotations

import pandas as pd

from app.indicators.technical import bollinger_bands
from app.strategies.base import Strategy, _crosses_above, _crosses_below


class BollingerBreakoutStrategy(Strategy):
    """Momentum breakout: long when price breaks above the upper band, short
    when it breaks below the lower band (if allow_short); exits back at the
    middle band (the moving average) in both cases."""

    def __init__(self, window: int = 20, num_std: float = 2.0, allow_short: bool = True):
        super().__init__(allow_short=allow_short)
        self.window = window
        self.num_std = num_std
        self.name = f"bollinger_breakout_{window}_{num_std}"

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        upper, middle, lower = bollinger_bands(df["Close"], self.window, self.num_std)
        df["bb_upper"] = upper
        df["bb_middle"] = middle
        df["bb_lower"] = lower
        return df

    def generate_signals(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        close = df["Close"]
        return {
            "long_entry": _crosses_above(close, df["bb_upper"]),
            "long_exit": _crosses_below(close, df["bb_middle"]),
            "short_entry": _crosses_below(close, df["bb_lower"]),
            "short_exit": _crosses_above(close, df["bb_middle"]),
        }

    def explain(self, df: pd.DataFrame) -> dict:
        last = df.iloc[-1]
        return {
            "close": round(float(last["Close"]), 4),
            "bb_upper": round(float(last["bb_upper"]), 4) if pd.notna(last["bb_upper"]) else None,
            "bb_middle": round(float(last["bb_middle"]), 4) if pd.notna(last["bb_middle"]) else None,
            "bb_lower": round(float(last["bb_lower"]), 4) if pd.notna(last["bb_lower"]) else None,
        }
