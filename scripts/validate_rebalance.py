"""Does quarterly portfolio re-selection close the gap against buy & hold?

The virgin-windows test (validate_frozen_windows.py) confirmed the frozen
model isn't overfit but also never beats the benchmark — and its main
structural suspect is marrying day one's picks for 3 years. This script runs
the same frozen model with rebalance_months=3 across all 9 windows (the 6
tuning-era ones plus the 3 virgin ones) and compares against the committed
baseline results:

- 6 tuned windows: the risk_regime arm of validate_risk_regime_result.json
  (that arm IS today's default model).
- 3 virgin windows: validate_frozen_windows_result.json.

Baselines are embedded rather than re-run because they're the committed,
already-reported numbers — re-running them would double the cost to
reproduce what's in git. Benchmarks are computed fresh per window by
_run_simulation itself (initial selection, bought day one, never touched).
"""

import json
import time

import pandas as pd

import app.portfolio as portfolio_module
from app.config import EXAMPLE_SYMBOLS
from app.data.providers import get_ohlcv

SYMBOLS = [entry["symbol"] for syms in EXAMPLE_SYMBOLS.values() for entry in syms]

# start_date -> (label, baseline total_return_pct of today's default model)
PERIODS = [
    ("2004-07-30", "2004-2007 (virgen)", 716.59),
    ("2007-07-30", "2007-2010 (crisis)", 18.66),
    ("2010-07-30", "2010-2013 (virgen)", 12.32),
    ("2012-07-30", "2012-2015 (virgen)", 23.16),
    ("2014-07-30", "2014-2017", 63.60),
    ("2017-07-30", "2017-2020 (COVID)", 54.46),
    ("2019-07-30", "2019-2022", 51.35),
    ("2021-07-30", "2021-2024", 20.59),
    ("2023-07-30", "2023-2026", 42.85),
]
WARMUP_YEARS = 2
SIMULATED_YEARS = 3
REBALANCE_MONTHS = 3

if __name__ == "__main__":
    import sys

    # Robustness sweep support: pass an interval (in months) as argv to
    # re-run the same 9-window comparison with it. The PRE-REGISTERED rule
    # for reading a sweep, decided before seeing any number: if every
    # interval beats the no-rebalance baseline, "re-selecting helps" is a
    # robust conclusion and the default stays 3 for its independent reasons
    # (earnings cycle, indicator horizons, rotation-cost amortization); if
    # ONLY 3 months wins, yesterday's result was parameter luck and the
    # default's credibility gets downgraded — not celebrated. The sweep is
    # never used to pick the highest-scoring interval as a new default.
    if len(sys.argv) > 1:
        REBALANCE_MONTHS = int(sys.argv[1])

    t0 = time.time()
    all_results = []
    for start_date, label, baseline_return in PERIODS:
        print(f"\n=== Periodo: {label} ({start_date} +3y) ===", flush=True)
        start_ts = pd.Timestamp(start_date)
        fetch_start = (start_ts - pd.DateOffset(years=WARMUP_YEARS)).date().isoformat()
        fetch_end = (start_ts + pd.DateOffset(years=SIMULATED_YEARS)).date().isoformat()

        dfs = {}
        for symbol in SYMBOLS:
            try:
                dfs[symbol] = get_ohlcv(symbol, start=fetch_start, end=fetch_end)
            except Exception:
                pass

        try:
            report = portfolio_module._run_simulation(
                dfs, start_date, None, 5, 10_000.0, None, False, 1, {},
                risk_regime_sizing=True,
                rebalance_months=REBALANCE_MONTHS,
            )
        except ValueError as exc:
            print(f"  Omitido: {exc}", flush=True)
            all_results.append({"period": label, "skipped": str(exc)})
            continue

        curve = pd.Series(
            [p["equity"] for p in report["portfolio_equity_curve"]],
            index=[p["date"] for p in report["portfolio_equity_curve"]],
        )
        running_max = curve.cummax()
        max_drawdown_pct = round(float(((curve - running_max) / running_max).min()) * 100, 2)

        entry = {
            "period": label,
            "rebalanced_return_pct": report["total_return_pct"],
            "rebalanced_max_drawdown_pct": max_drawdown_pct,
            "baseline_return_pct": baseline_return,
            "return_delta_pp": round(report["total_return_pct"] - baseline_return, 2),
            "benchmark_return_pct": report["benchmark_buy_hold"]["total_return_pct"],
            "vs_benchmark_pct_points": report["vs_benchmark_pct_points"],
            "num_segments": len(report["segments"]),
            "num_cash_segments": sum(1 for s in report["segments"] if not s["portfolio"]),
            "segment_portfolios": [s["portfolio"] for s in report["segments"]],
        }
        all_results.append(entry)
        print(f"  REBALANCEADO: {entry['rebalanced_return_pct']}% (DD {max_drawdown_pct}%), {entry['num_segments']} segmentos ({entry['num_cash_segments']} en efectivo)", flush=True)
        print(f"  BASELINE (sin rebalanceo): {baseline_return}% | delta: {entry['return_delta_pp']} pp", flush=True)
        print(f"  BUY&HOLD: {entry['benchmark_return_pct']}% | vs benchmark: {entry['vs_benchmark_pct_points']} pp", flush=True)

    elapsed = time.time() - t0
    ran = [r for r in all_results if "skipped" not in r]
    beats_baseline = sum(1 for r in ran if r["return_delta_pp"] > 0)
    beats_benchmark = sum(1 for r in ran if r["vs_benchmark_pct_points"] > 0)
    avg_delta = round(sum(r["return_delta_pp"] for r in ran) / len(ran), 2) if ran else None
    summary = {
        "elapsed_seconds": round(elapsed, 1),
        "rebalance_months": REBALANCE_MONTHS,
        "num_periods_run": len(ran),
        "num_beats_baseline": beats_baseline,
        "num_beats_benchmark": beats_benchmark,
        "avg_return_delta_pp_vs_baseline": avg_delta,
        "results": all_results,
    }
    out_name = (
        "scripts/validate_rebalance_result.json"
        if REBALANCE_MONTHS == 3
        else f"scripts/validate_rebalance_result_{REBALANCE_MONTHS}m.json"
    )
    with open(out_name, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n=== RESUMEN: rebalanceo trimestral le gana al modelo actual en {beats_baseline}/{len(ran)} ventanas (delta promedio {avg_delta} pp) y al buy & hold en {beats_benchmark}/{len(ran)} ===", flush=True)
    print(f"elapsed_seconds={elapsed:.1f}", flush=True)
