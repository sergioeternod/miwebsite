from __future__ import annotations

import pandas as pd

from app.indicators.technical import rsi
from app.strategies.base import Strategy


class RsiMeanReversionStrategy(Strategy):
    """Mean reversion: long a confirmed bounce off oversold, short a confirmed
    turn down from overbought (if allow_short) — and exit either side when the
    RSI returns to its midline.

    The midline exit is what makes this actually mean-reversion. An earlier
    version exited each side only at the *opposite extreme* (shorts closed on
    an oversold bounce, longs on an overbought turn), which in a sustained
    uptrend is a one-way trap: entering short is easy (RSI dips through
    overbought on every pullback) but the exit condition (an oversold bounce)
    almost never fires, so the strategy sat short for months against the
    trend — measured on real data, 65-76% of days short on instruments that
    rose 25-71% over the period, including a single 374-bar short on gold
    that lost -46.8%. A reversion trade's thesis is "price returns to the
    mean"; once RSI is back at the midline the thesis has played out, win or
    lose, and staying in the trade is no longer reversion — it's an
    unmanaged directional bet."""

    def __init__(
        self,
        window: int = 14,
        oversold: float = 30,
        overbought: float = 70,
        midline: float = 50,
        allow_short: bool = True,
    ):
        super().__init__(allow_short=allow_short)
        if oversold >= overbought:
            raise ValueError("oversold debe ser menor que overbought")
        if not (oversold < midline < overbought):
            raise ValueError("midline debe estar entre oversold y overbought")
        self.window = window
        self.oversold = oversold
        self.overbought = overbought
        self.midline = midline
        self.name = f"rsi_reversion_{window}_{int(oversold)}_{int(overbought)}"

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["rsi"] = rsi(df["Close"], self.window)
        return df

    def generate_signals(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        rsi_series = df["rsi"]
        prev = rsi_series.shift(1)
        # Bottom confirmed: RSI bounces back up through the oversold line.
        bottom_reversal = (rsi_series >= self.oversold) & (prev < self.oversold)
        # Top confirmed: RSI turns back down through the overbought line.
        top_reversal = (rsi_series < self.overbought) & (prev >= self.overbought)
        # Mean reached: RSI crosses back through the midline (from either side).
        recovers_to_mid = (rsi_series >= self.midline) & (prev < self.midline)
        falls_to_mid = (rsi_series <= self.midline) & (prev > self.midline)
        return {
            "long_entry": bottom_reversal,
            "long_exit": recovers_to_mid | top_reversal,
            "short_entry": top_reversal,
            "short_exit": falls_to_mid | bottom_reversal,
        }

    def explain(self, df: pd.DataFrame) -> dict:
        last = df.iloc[-1]
        return {
            "rsi": round(float(last["rsi"]), 2) if pd.notna(last["rsi"]) else None,
            "oversold": self.oversold,
            "overbought": self.overbought,
            "midline": self.midline,
        }
