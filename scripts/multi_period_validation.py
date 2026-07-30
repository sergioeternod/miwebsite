"""Out-of-sample robustness check: does risk-adjusted (Sharpe/drawdown-aware)
portfolio selection consistently beat plain-confidence selection, or did the
2023-07-30 -> 2026-07-30 result just get lucky on one period?

Runs the same comparison across 3 non-overlapping 3-year windows (a bear
stretch, a mixed/recovery stretch, and the period already tested), all on
real market data, reusing already-fetched full-history data across periods
to avoid re-hitting the network 3x, and reusing already-computed
walk-forward results for any symbol that both the old and new selection
picked (so the two methods aren't computed twice for the same symbol).
"""

import json
import time

import pandas as pd

from app.config import EXAMPLE_SYMBOLS
from app.data.providers import get_ohlcv
from app.portfolio import (
    MIN_WARMUP_BARS,
    _combine_equity_curves,
    _find_start_index,
    _select_portfolio,
    _walk_forward_result,
)
from app.recommend.engine import recommend

SYMBOLS = [entry["symbol"] for syms in EXAMPLE_SYMBOLS.values() for entry in syms]

# Each period fetches its own bounded [warmup_start, end] window (~2y warmup
# + 3y simulated = ~5y of data) instead of "max" history — pulling full
# history for old symbols (^GSPC goes back to 1927) would make each daily
# recommend() call inside the walk-forward progressively slower as the
# window balloons, turning an ~11-minute run into a multi-hour one for no
# added rigor (the ensemble already only looks 2 years back for its
# strategy backtests either way).
PERIODS = [
    {"label": "2017-07-30 -> 2020-07-30 (bajista/mixto)", "start_date": "2017-07-30"},
    {"label": "2019-07-30 -> 2022-07-30 (covid + recuperación + inicio bajista 2022)", "start_date": "2019-07-30"},
    {"label": "2023-07-30 -> 2026-07-30 (ya corrida antes)", "start_date": "2023-07-30"},
]
WARMUP_YEARS = 2
SIMULATED_YEARS = 3
PORTFOLIO_SIZE = 5
INITIAL_CAPITAL = 10_000.0
STEP = 1


def select_old_style(dfs, start_idx_by_symbol, portfolio_size):
    """Replicates the pre-existing pure-confidence ranking (no risk
    adjustment), for comparison only — production code no longer has this
    path."""
    candidates = []
    for symbol, df in dfs.items():
        idx = start_idx_by_symbol[symbol]
        if idx < MIN_WARMUP_BARS:
            continue
        window = df.iloc[:idx]
        rec = recommend(window, symbol=symbol, initial_capital=INITIAL_CAPITAL, commission_bps=None, allow_short=True)
        if rec["overall_action"] in {"BUY", "SELL"} and rec["confidence_pct"] >= 55.0:
            candidates.append(
                {"symbol": symbol, "action_at_selection": rec["overall_action"], "confidence_pct_at_selection": rec["confidence_pct"]}
            )
    candidates.sort(key=lambda c: c["confidence_pct_at_selection"], reverse=True)
    return candidates[:portfolio_size]


def run_portfolio(dfs, start_idx_by_symbol, portfolio, walk_forward_cache):
    capital_per_symbol = round(INITIAL_CAPITAL / len(portfolio), 2)
    results = []
    for c in portfolio:
        symbol = c["symbol"]
        if symbol not in walk_forward_cache:
            walk_forward_cache[symbol] = _walk_forward_result(
                dfs[symbol], start_idx_by_symbol[symbol], symbol, True, capital_per_symbol, None, STEP
            )
        results.append(walk_forward_cache[symbol])
    equity_curve = _combine_equity_curves(results, capital_per_symbol)
    final_equity = round(float(equity_curve.iloc[-1]), 2)
    return {
        "final_equity": final_equity,
        "total_pnl_amount": round(final_equity - INITIAL_CAPITAL, 2),
        "total_return_pct": round((final_equity / INITIAL_CAPITAL - 1) * 100, 2),
    }


if __name__ == "__main__":
    t0 = time.time()

    all_results = []
    all_errors = {}
    for period in PERIODS:
        print(f"\n=== Periodo: {period['label']} ===")
        start_ts = pd.Timestamp(period["start_date"])
        fetch_start = (start_ts - pd.DateOffset(years=WARMUP_YEARS)).date().isoformat()
        fetch_end = (start_ts + pd.DateOffset(years=SIMULATED_YEARS)).date().isoformat()

        print(f"  Fetching {fetch_start} -> {fetch_end} for {len(SYMBOLS)} symbols...")
        dfs = {}
        errors = {}
        for symbol in SYMBOLS:
            try:
                dfs[symbol] = get_ohlcv(symbol, start=fetch_start, end=fetch_end)
            except Exception as exc:
                errors[symbol] = str(exc)
        all_errors[period["start_date"]] = errors
        print(f"  Fetched {len(dfs)}/{len(SYMBOLS)} symbols, {len(errors)} errors.")

        start_idx_by_symbol = {s: _find_start_index(df, period["start_date"]) for s, df in dfs.items()}
        usable = {s: df for s, df in dfs.items() if MIN_WARMUP_BARS <= start_idx_by_symbol[s] < len(df) - 1}

        old_portfolio = select_old_style(usable, start_idx_by_symbol, PORTFOLIO_SIZE)
        new_portfolio = _select_portfolio(
            usable, start_idx_by_symbol, PORTFOLIO_SIZE, True, INITIAL_CAPITAL, None, 55.0
        )

        if not old_portfolio or not new_portfolio:
            print("  Sin candidatos suficientes en este periodo, se omite.")
            continue

        walk_forward_cache = {}
        old_result = run_portfolio(usable, start_idx_by_symbol, old_portfolio, walk_forward_cache)
        new_result = run_portfolio(usable, start_idx_by_symbol, new_portfolio, walk_forward_cache)

        entry = {
            "period": period["label"],
            "start_date": period["start_date"],
            "old_portfolio": [c["symbol"] for c in old_portfolio],
            "old_result": old_result,
            "new_portfolio": [c["symbol"] for c in new_portfolio],
            "new_result": new_result,
            "improved": new_result["total_return_pct"] > old_result["total_return_pct"],
        }
        all_results.append(entry)
        print(f"  OLD {entry['old_portfolio']}: {old_result['total_pnl_amount']} ({old_result['total_return_pct']}%)")
        print(f"  NEW {entry['new_portfolio']}: {new_result['total_pnl_amount']} ({new_result['total_return_pct']}%)")
        print(f"  {'MEJORÓ' if entry['improved'] else 'NO MEJORÓ'}")

    elapsed = time.time() - t0
    num_improved = sum(1 for r in all_results if r["improved"])
    summary = {
        "elapsed_seconds": round(elapsed, 1),
        "num_periods_tested": len(all_results),
        "num_periods_improved": num_improved,
        "results": all_results,
        "fetch_errors": all_errors,
    }
    with open("scripts/multi_period_validation_result.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n\n=== RESUMEN: {num_improved}/{len(all_results)} periodos mejoraron con selección ajustada por riesgo ===")
    print(f"elapsed_seconds={elapsed:.1f}")
