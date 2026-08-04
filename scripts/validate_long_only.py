"""Does dropping shorts entirely beat the current model? The measured
asymmetry (longs profitable in every saved multi-year run, shorts losing in
every one) suggests the boldest test first: same full risk stack, but
allow_short=False, across the same 5 historical windows used by
multi_period_validation.py. Long-only is the limit case of
short_confidence_premium -> infinity; if it wins broadly, sweeping premium
values in between is refinement, not discovery."""

import json
import time

import pandas as pd

from app.config import EXAMPLE_SYMBOLS
from app.data.providers import get_ohlcv
from app.portfolio import (
    MIN_WARMUP_BARS,
    _combine_equity_curves,
    _find_start_index,
    _risk_parity_weights,
    _select_portfolio,
    _walk_forward_result,
)

SYMBOLS = [entry["symbol"] for syms in EXAMPLE_SYMBOLS.values() for entry in syms]
PERIODS = [
    {"label": "2014-07-30 -> 2017-07-30", "start_date": "2014-07-30"},
    {"label": "2017-07-30 -> 2020-07-30", "start_date": "2017-07-30"},
    {"label": "2019-07-30 -> 2022-07-30", "start_date": "2019-07-30"},
    {"label": "2021-07-30 -> 2024-07-30", "start_date": "2021-07-30"},
    {"label": "2023-07-30 -> 2026-07-30", "start_date": "2023-07-30"},
]
WARMUP_YEARS = 2
SIMULATED_YEARS = 3
PORTFOLIO_SIZE = 5
INITIAL_CAPITAL = 10_000.0
STEP = 1


def run_arm(usable, start_idx_by_symbol, allow_short):
    portfolio = _select_portfolio(
        usable, start_idx_by_symbol, PORTFOLIO_SIZE, allow_short, INITIAL_CAPITAL, None, 55.0
    )
    if not portfolio:
        return None
    weights = _risk_parity_weights(portfolio)
    capital_by_symbol = {s: round(INITIAL_CAPITAL * w, 2) for s, w in weights.items()}
    results = [
        _walk_forward_result(
            usable[c["symbol"]], start_idx_by_symbol[c["symbol"]], c["symbol"], allow_short,
            capital_by_symbol[c["symbol"]], None, STEP,
        )
        for c in portfolio
    ]
    equity_curve = _combine_equity_curves(results, capital_by_symbol)
    final_equity = round(float(equity_curve.iloc[-1]), 2)
    return {
        "portfolio": [c["symbol"] for c in portfolio],
        "final_equity": final_equity,
        "total_pnl_amount": round(final_equity - INITIAL_CAPITAL, 2),
        "total_return_pct": round((final_equity / INITIAL_CAPITAL - 1) * 100, 2),
    }


if __name__ == "__main__":
    import sys

    # Optional: pass start dates as argv to test other windows (e.g. the
    # 2007-2010 financial-crisis stress window) without editing the file.
    if len(sys.argv) > 1:
        PERIODS = [{"label": f"{d} (+3y)", "start_date": d} for d in sys.argv[1:]]

    t0 = time.time()
    all_results = []
    for period in PERIODS:
        print(f"\n=== Periodo: {period['label']} ===")
        start_ts = pd.Timestamp(period["start_date"])
        fetch_start = (start_ts - pd.DateOffset(years=WARMUP_YEARS)).date().isoformat()
        fetch_end = (start_ts + pd.DateOffset(years=SIMULATED_YEARS)).date().isoformat()

        dfs = {}
        for symbol in SYMBOLS:
            try:
                dfs[symbol] = get_ohlcv(symbol, start=fetch_start, end=fetch_end)
            except Exception:
                pass
        start_idx_by_symbol = {s: _find_start_index(df, period["start_date"]) for s, df in dfs.items()}
        usable = {s: df for s, df in dfs.items() if MIN_WARMUP_BARS <= start_idx_by_symbol[s] < len(df) - 1}

        with_shorts = run_arm(usable, start_idx_by_symbol, allow_short=True)
        long_only = run_arm(usable, start_idx_by_symbol, allow_short=False)

        if with_shorts is None or long_only is None:
            print("  Sin candidatos suficientes en algún brazo, se omite.")
            continue

        entry = {
            "period": period["label"],
            "with_shorts": with_shorts,
            "long_only": long_only,
            "long_only_better": long_only["total_return_pct"] > with_shorts["total_return_pct"],
        }
        all_results.append(entry)
        print(f"  CON SHORTS {with_shorts['portfolio']}: {with_shorts['total_pnl_amount']} ({with_shorts['total_return_pct']}%)")
        print(f"  LONG-ONLY  {long_only['portfolio']}: {long_only['total_pnl_amount']} ({long_only['total_return_pct']}%)")
        print(f"  {'LONG-ONLY GANA' if entry['long_only_better'] else 'CON SHORTS GANA'}")

    elapsed = time.time() - t0
    num_long_only_better = sum(1 for r in all_results if r["long_only_better"])
    deltas = [r["long_only"]["total_return_pct"] - r["with_shorts"]["total_return_pct"] for r in all_results]
    avg_delta = round(sum(deltas) / len(deltas), 2) if deltas else None
    summary = {
        "elapsed_seconds": round(elapsed, 1),
        "num_periods": len(all_results),
        "num_long_only_better": num_long_only_better,
        "avg_return_pct_delta_long_only_minus_shorts": avg_delta,
        "results": all_results,
    }
    out_name = "scripts/validate_long_only_result.json" if len(sys.argv) <= 1 else "scripts/validate_long_only_extra_result.json"
    with open(out_name, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n=== RESUMEN: long-only gana en {num_long_only_better}/{len(all_results)} periodos, delta promedio {avg_delta} pp ===")
    print(f"elapsed_seconds={elapsed:.1f}")
