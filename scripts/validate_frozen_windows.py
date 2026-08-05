"""The overfitting test the model owes us: every validation so far reused
the same 6 historical windows that also guided each improvement, so their
value as evidence has been eroding with every "validated" change. This
script freezes the model exactly as it ships today — long-only, risk-parity
sizing, risk-regime exposure scaling, 15% stop-loss, confidence threshold
55 with adaptive regret — and runs it on windows NEVER used for tuning:
2004-2007, 2010-2013, 2012-2015.

Nothing here feeds back into the model. Whatever comes out — good or bad —
gets reported as-is; a frozen model that only shines on the windows it was
tuned on is overfit, and better to learn that here than with real money.

Each window also reports the buy & hold benchmark on the same selected
portfolio, because "made money" is not the bar — "beat doing nothing" is.
"""

import json
import time

import pandas as pd

from app.config import EXAMPLE_SYMBOLS
from app.data.providers import get_ohlcv
from app.portfolio import (
    MIN_WARMUP_BARS,
    _buy_hold_benchmark,
    _combine_equity_curves,
    _find_start_index,
    _risk_parity_weights,
    _select_portfolio,
    _walk_forward_result,
)

SYMBOLS = [entry["symbol"] for syms in EXAMPLE_SYMBOLS.values() for entry in syms]
PERIODS = [
    {"label": "2004-07-30 -> 2007-07-30", "start_date": "2004-07-30"},
    {"label": "2010-07-30 -> 2013-07-30", "start_date": "2010-07-30"},
    {"label": "2012-07-30 -> 2015-07-30", "start_date": "2012-07-30"},
]
WARMUP_YEARS = 2
SIMULATED_YEARS = 3
PORTFOLIO_SIZE = 5
INITIAL_CAPITAL = 10_000.0
STEP = 1

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        PERIODS = [{"label": f"{d} (+3y)", "start_date": d} for d in sys.argv[1:]]

    t0 = time.time()
    all_results = []
    for period in PERIODS:
        print(f"\n=== Periodo: {period['label']} ===", flush=True)
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
        print(f"  Símbolos con historial suficiente: {len(usable)}/{len(SYMBOLS)}", flush=True)

        # Frozen defaults: long-only, min confidence 55 — same call shape as
        # _run_simulation makes for the shipping model.
        portfolio = _select_portfolio(
            usable, start_idx_by_symbol, PORTFOLIO_SIZE, False, INITIAL_CAPITAL, None, 55.0
        )
        if not portfolio:
            print("  Sin candidatos BUY >=55% antes de la fecha de inicio, se omite.", flush=True)
            all_results.append({"period": period["label"], "skipped": "sin candidatos"})
            continue

        weights = _risk_parity_weights(portfolio)
        capital_by_symbol = {s: round(INITIAL_CAPITAL * w, 2) for s, w in weights.items()}
        results = [
            _walk_forward_result(
                usable[c["symbol"]], start_idx_by_symbol[c["symbol"]], c["symbol"], False,
                capital_by_symbol[c["symbol"]], None, STEP,
                risk_regime_sizing=True,
            )
            for c in portfolio
        ]
        equity_curve = _combine_equity_curves(results, capital_by_symbol)
        final_equity = round(float(equity_curve.iloc[-1]), 2)
        total_return_pct = round((final_equity / INITIAL_CAPITAL - 1) * 100, 2)
        running_max = equity_curve.cummax()
        max_drawdown_pct = round(float(((equity_curve - running_max) / running_max).min()) * 100, 2)

        selected = {c["symbol"]: usable[c["symbol"]] for c in portfolio}
        benchmark = _buy_hold_benchmark(selected, start_idx_by_symbol, capital_by_symbol, None)

        entry = {
            "period": period["label"],
            "portfolio": [c["symbol"] for c in portfolio],
            "final_equity": final_equity,
            "total_return_pct": total_return_pct,
            "max_drawdown_pct": max_drawdown_pct,
            "benchmark_buy_hold_return_pct": benchmark["total_return_pct"],
            "vs_benchmark_pct_points": round(total_return_pct - benchmark["total_return_pct"], 2),
        }
        all_results.append(entry)
        print(f"  MODELO    {entry['portfolio']}: {total_return_pct}% (max DD {max_drawdown_pct}%)", flush=True)
        print(f"  BUY&HOLD  {benchmark['total_return_pct']}% | vs benchmark: {entry['vs_benchmark_pct_points']} pp", flush=True)

    elapsed = time.time() - t0
    ran = [r for r in all_results if "skipped" not in r]
    positive = sum(1 for r in ran if r["total_return_pct"] > 0)
    beat_bench = sum(1 for r in ran if r["vs_benchmark_pct_points"] > 0)
    summary = {
        "elapsed_seconds": round(elapsed, 1),
        "num_periods_run": len(ran),
        "num_positive_return": positive,
        "num_beat_benchmark": beat_bench,
        "results": all_results,
    }
    with open("scripts/validate_frozen_windows_result.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n=== RESUMEN: retorno positivo en {positive}/{len(ran)}, le gana al buy & hold en {beat_bench}/{len(ran)} ===", flush=True)
    print(f"elapsed_seconds={elapsed:.1f}", flush=True)
