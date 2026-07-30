"""Per-trade directional accuracy: every trade a strategy takes is an implicit
bet on direction (long = "expects price to rise", short = "expects price to
fall"). This annotates each trade with that expectation and whether reality
(the realized return) matched it, then aggregates a hit rate — a more
granular, explicit view of the same information win_rate summarizes.

`annotate_trade_hindsight` goes a step further than hit/miss: for each
closed trade, it asks "was the position actually taken (long/short) the
*best* of the three options available (long/short/flat) over that same
entry-to-exit window?" — a look back at old positions to identify whether a
better one existed, not a live signal (there's no way to know an exit price
before it happens).
"""

from __future__ import annotations

import pandas as pd

from app.backtest.engine import run_backtest
from app.strategies.base import Strategy


def annotate_trade_hits(trades: list[dict]) -> list[dict]:
    annotated = []
    for t in trades:
        expected_direction = "sube" if t["direction"] == "long" else "baja"
        annotated.append({**t, "expected_direction": expected_direction, "hit": t["return_pct"] > 0})
    return annotated


def _hit_rate(trades: list[dict]) -> float | None:
    if not trades:
        return None
    return round(sum(1 for t in trades if t["hit"]) / len(trades) * 100, 2)


def directional_accuracy(trades: list[dict]) -> dict:
    annotated = annotate_trade_hits(trades)
    long_trades = [t for t in annotated if t["direction"] == "long"]
    short_trades = [t for t in annotated if t["direction"] == "short"]
    return {
        "num_trades": len(annotated),
        "hit_rate_pct": _hit_rate(annotated) or 0.0,
        "num_long": len(long_trades),
        "long_hit_rate_pct": _hit_rate(long_trades),
        "num_short": len(short_trades),
        "short_hit_rate_pct": _hit_rate(short_trades),
    }


def strategy_directional_accuracy(
    df: pd.DataFrame,
    strategy: Strategy,
    symbol: str = "",
    initial_capital: float = 10_000.0,
    commission_bps: float | None = None,
) -> dict:
    result = run_backtest(
        df, strategy, symbol=symbol, initial_capital=initial_capital, commission_bps=commission_bps
    )
    return {
        "strategy": strategy.name,
        "accuracy": directional_accuracy(result.trades),
        "trades": annotate_trade_hits(result.trades),
    }


def compare_directional_accuracy(
    df: pd.DataFrame,
    strategies: list[Strategy],
    symbol: str = "",
    initial_capital: float = 10_000.0,
    commission_bps: float | None = None,
) -> list[dict]:
    return [
        strategy_directional_accuracy(
            df, s, symbol=symbol, initial_capital=initial_capital, commission_bps=commission_bps
        )
        for s in strategies
    ]


def annotate_trade_hindsight(trades: list[dict], commission_bps: float = 0.0) -> list[dict]:
    """For each closed trade, estimates — from entry/exit price alone —
    whether staying flat or taking the opposite direction would have done
    better than the position actually taken.

    This is a coarser, price-ratio-based estimate than the trade's own
    equity-curve-derived `return_pct` (see `app.backtest.engine.extract_trades`
    and its note on short-trade "compounding drag"): all three candidates
    (long/short/flat) are computed the same simplified way here, so the
    *comparison* between them is fair even though the "actual" candidate's
    number may not exactly match the trade's own `return_pct`. This answers
    "was there a better position?", not "exactly how many more dollars, to
    the cent" — `missed_pnl_amount` is likewise an estimate, scaled off the
    trade's own `equity_at_entry` when available.

    Open (still-unrealized) trades are skipped — there's no exit price yet
    to compare against — and come back with `"hindsight": None`.
    """
    commission_rate = commission_bps / 10000
    annotated = []
    for t in trades:
        if t.get("open"):
            annotated.append({**t, "hindsight": None})
            continue

        long_return_pct = (t["exit_price"] / t["entry_price"] - 1) * 100 - 2 * commission_rate * 100
        short_return_pct = (t["entry_price"] / t["exit_price"] - 1) * 100 - 2 * commission_rate * 100
        candidates = {"long": long_return_pct, "short": short_return_pct, "flat": 0.0}

        actual_return_pct = candidates[t["direction"]]
        best_direction = max(candidates, key=candidates.get)
        best_return_pct = candidates[best_direction]
        regret_pct = round(max(best_return_pct - actual_return_pct, 0.0), 2)

        equity_at_entry = t.get("equity_at_entry")
        missed_pnl_amount = round(regret_pct / 100 * equity_at_entry, 2) if equity_at_entry is not None else None

        annotated.append(
            {
                **t,
                "hindsight": {
                    "best_direction": best_direction,
                    "best_return_pct": round(best_return_pct, 2),
                    "regret_pct": regret_pct,
                    "was_optimal": regret_pct <= 0.01,
                    "missed_pnl_amount": missed_pnl_amount,
                },
            }
        )
    return annotated


def hindsight_summary(annotated_trades: list[dict]) -> dict:
    """Aggregates `annotate_trade_hindsight`'s per-trade output into a report
    card: how much of the past decision-making was actually the best
    available option, in hindsight. Not a forecast — a look back."""
    closed = [t for t in annotated_trades if t.get("hindsight") is not None]
    if not closed:
        return {
            "num_trades": 0,
            "num_optimal": 0,
            "pct_optimal": None,
            "avg_regret_pct": None,
            "total_missed_pnl_amount": None,
        }

    num_optimal = sum(1 for t in closed if t["hindsight"]["was_optimal"])
    avg_regret_pct = sum(t["hindsight"]["regret_pct"] for t in closed) / len(closed)
    missed_amounts = [t["hindsight"]["missed_pnl_amount"] for t in closed if t["hindsight"]["missed_pnl_amount"] is not None]

    return {
        "num_trades": len(closed),
        "num_optimal": num_optimal,
        "pct_optimal": round(num_optimal / len(closed) * 100, 1),
        "avg_regret_pct": round(avg_regret_pct, 2),
        "total_missed_pnl_amount": round(sum(missed_amounts), 2) if missed_amounts else None,
    }
