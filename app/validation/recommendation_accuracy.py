"""Walk-forward validation of the recommendation engine: recompute the
ensemble recommendation at many historical points in time, using only data
available up to and including that point (no lookahead — the same slice a
live user would have had), then compare the call (BUY/SELL/HOLD) against
what the price actually did over the following `horizon` bars.
"""

from __future__ import annotations

import pandas as pd

from app.recommend.engine import recommend


def walk_forward_recommendation_accuracy(
    df: pd.DataFrame,
    symbol: str = "",
    horizon: int = 10,
    step: int = 10,
    warmup: int = 110,
    allow_short: bool = True,
    initial_capital: float = 10_000.0,
    commission_bps: float = 5.0,
) -> dict:
    if horizon < 1 or step < 1:
        raise ValueError("horizon y step deben ser >= 1")

    n = len(df)
    records = []
    t = warmup
    while t + horizon < n:
        window = df.iloc[: t + 1]
        rec = recommend(
            window,
            symbol=symbol,
            initial_capital=initial_capital,
            commission_bps=commission_bps,
            allow_short=allow_short,
        )
        entry_price = float(df["Close"].iloc[t])
        future_price = float(df["Close"].iloc[t + horizon])
        forward_return_pct = (future_price / entry_price - 1) * 100
        records.append(
            {
                "date": str(df.index[t]),
                "action": rec["overall_action"],
                "confidence_pct": rec["confidence_pct"],
                "entry_price": entry_price,
                "future_price": future_price,
                "forward_return_pct": round(forward_return_pct, 2),
            }
        )
        t += step

    return {
        "symbol": symbol,
        "horizon_bars": horizon,
        "step_bars": step,
        "num_evaluations": len(records),
        "records": records,
        "summary": _summarize(records),
    }


def _avg_forward_return(records: list[dict]) -> float | None:
    return round(sum(r["forward_return_pct"] for r in records) / len(records), 2) if records else None


def _hit_rate(records: list[dict], expect_up: bool) -> float | None:
    if not records:
        return None
    hits = sum(1 for r in records if (r["forward_return_pct"] > 0) == expect_up)
    return round(hits / len(records) * 100, 2)


def _summarize(records: list[dict]) -> dict:
    buy = [r for r in records if r["action"] == "BUY"]
    sell = [r for r in records if r["action"] == "SELL"]
    hold = [r for r in records if r["action"] == "HOLD"]

    return {
        "buy": {
            "count": len(buy),
            "avg_forward_return_pct": _avg_forward_return(buy),
            "hit_rate_pct": _hit_rate(buy, expect_up=True),
        },
        "sell": {
            "count": len(sell),
            "avg_forward_return_pct": _avg_forward_return(sell),
            "hit_rate_pct": _hit_rate(sell, expect_up=False),
        },
        "hold": {
            "count": len(hold),
            "avg_forward_return_pct": _avg_forward_return(hold),
        },
    }
