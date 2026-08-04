"""Does risk-regime position sizing (scale exposure down while short-window
realized volatility runs above its long-window baseline — see
app.portfolio._vol_regime_exposure) improve the current long-only default?

Motivation (measured, not assumed): this engine's own record shows crashes
weren't predictable — the eve of the Aug-2024 drop read HOLD with RSI already
reacting, and the Jan-2026 peak read HOLD 80.6% with zero warning. So the
indicator doesn't try to predict; it shrinks how much a volatile stretch
hurts. Whether that *nets* positive (volatile stretches also contain sharp
rebounds, which scaled-down exposure participates in less) is exactly what
this script measures, across the same 5 historical windows used by
multi_period_validation.py plus the 2007-2010 financial-crisis stress window.

Both arms are the current default model (long-only, full risk stack); the
only difference is risk_regime_sizing on/off. Entries and exits are identical
by construction — the regime filter only scales exposure — so any delta is
purely the sizing effect plus its commission drag.
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
    _risk_parity_weights,
    _select_portfolio,
    _walk_forward_result,
)

SYMBOLS = [entry["symbol"] for syms in EXAMPLE_SYMBOLS.values() for entry in syms]
PERIODS = [
    {"label": "2007-07-30 -> 2010-07-30 (crisis)", "start_date": "2007-07-30"},
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
ALLOW_SHORT = False  # current validated default (long-only won 6/6 windows)


def run_arm(usable, start_idx_by_symbol, portfolio, risk_regime_sizing):
    weights = _risk_parity_weights(portfolio)
    capital_by_symbol = {s: round(INITIAL_CAPITAL * w, 2) for s, w in weights.items()}
    results = [
        _walk_forward_result(
            usable[c["symbol"]], start_idx_by_symbol[c["symbol"]], c["symbol"], ALLOW_SHORT,
            capital_by_symbol[c["symbol"]], None, STEP,
            risk_regime_sizing=risk_regime_sizing,
        )
        for c in portfolio
    ]
    equity_curve = _combine_equity_curves(results, capital_by_symbol)
    final_equity = round(float(equity_curve.iloc[-1]), 2)
    running_max = equity_curve.cummax()
    max_drawdown_pct = round(float(((equity_curve - running_max) / running_max).min()) * 100, 2)
    return {
        "portfolio": [c["symbol"] for c in portfolio],
        "final_equity": final_equity,
        "total_pnl_amount": round(final_equity - INITIAL_CAPITAL, 2),
        "total_return_pct": round((final_equity / INITIAL_CAPITAL - 1) * 100, 2),
        "max_drawdown_pct": max_drawdown_pct,
        "avg_exposure_pct_by_symbol": {
            r["symbol"]: r["risk_regime_avg_exposure_pct"] for r in results
        },
    }


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

        # One selection shared by both arms: the regime filter only changes
        # sizing during the walk-forward, never which symbols get picked, so
        # selecting twice would just double the cost for an identical answer.
        portfolio = _select_portfolio(
            usable, start_idx_by_symbol, PORTFOLIO_SIZE, ALLOW_SHORT, INITIAL_CAPITAL, None, 55.0
        )
        if not portfolio:
            print("  Sin candidatos, se omite.", flush=True)
            continue

        baseline = run_arm(usable, start_idx_by_symbol, portfolio, risk_regime_sizing=False)
        regime = run_arm(usable, start_idx_by_symbol, portfolio, risk_regime_sizing=True)

        entry = {
            "period": period["label"],
            "baseline": baseline,
            "risk_regime": regime,
            "return_delta_pp": round(regime["total_return_pct"] - baseline["total_return_pct"], 2),
            "drawdown_delta_pp": round(regime["max_drawdown_pct"] - baseline["max_drawdown_pct"], 2),
            "risk_regime_better_return": regime["total_return_pct"] > baseline["total_return_pct"],
            "risk_regime_smaller_drawdown": regime["max_drawdown_pct"] > baseline["max_drawdown_pct"],
        }
        all_results.append(entry)
        print(f"  BASELINE    {baseline['portfolio']}: {baseline['total_pnl_amount']} ({baseline['total_return_pct']}%), max DD {baseline['max_drawdown_pct']}%", flush=True)
        print(f"  RISK-REGIME {regime['portfolio']}: {regime['total_pnl_amount']} ({regime['total_return_pct']}%), max DD {regime['max_drawdown_pct']}%", flush=True)
        print(f"  delta retorno: {entry['return_delta_pp']} pp | delta drawdown: {entry['drawdown_delta_pp']} pp", flush=True)

    elapsed = time.time() - t0
    n = len(all_results)
    wins_return = sum(1 for r in all_results if r["risk_regime_better_return"])
    wins_drawdown = sum(1 for r in all_results if r["risk_regime_smaller_drawdown"])
    return_deltas = [r["return_delta_pp"] for r in all_results]
    dd_deltas = [r["drawdown_delta_pp"] for r in all_results]
    summary = {
        "elapsed_seconds": round(elapsed, 1),
        "num_periods": n,
        "num_risk_regime_better_return": wins_return,
        "num_risk_regime_smaller_drawdown": wins_drawdown,
        "avg_return_delta_pp": round(sum(return_deltas) / n, 2) if n else None,
        "avg_drawdown_delta_pp": round(sum(dd_deltas) / n, 2) if n else None,
        "results": all_results,
    }
    with open("scripts/validate_risk_regime_result.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n=== RESUMEN: risk-regime mejora retorno en {wins_return}/{n} y reduce drawdown en {wins_drawdown}/{n} periodos ===", flush=True)
    print(f"delta retorno promedio: {summary['avg_return_delta_pp']} pp | delta drawdown promedio: {summary['avg_drawdown_delta_pp']} pp", flush=True)
    print(f"elapsed_seconds={elapsed:.1f}", flush=True)
