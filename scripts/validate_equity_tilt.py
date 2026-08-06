"""Does the equity-regime tilt (go 100% stocks/indexes while the S&P 500
trades above its 200-day moving average) close the gap against the pure
equity indexes without giving up the model's crash protection?

Motivation (measured): Aug-2025→Aug-2026 the model made +7.6% while the
indexes made +22-26%; the drag came from forex/gold picks that barely moved
in a strong equity year. The user's bar is explicit: beating the main
indexes. The tilt is the causal, classic answer — trend filter on the broad
market, knowable at each (re)selection boundary, no lookahead.

PRE-REGISTERED RULE, written before seeing any number:

- Arm B (current default + equity_regime_tilt) is compared against arm A
  (current default: long-only, risk-regime, quarterly rebalance) across all
  9 windows, AND against the S&P 500's own buy & hold return per window —
  the index the user wants beaten.
- ADOPT the tilt as default only if it beats arm A in a majority of the 9
  windows AND does not catastrophically worsen the crisis windows
  (2007-2010, 2017-2020): those two are the reason this model exists, and
  a tilt that wins bull years by giving back the crash protection is a
  worse model wearing better averages.
- The vs-index comparison is reported for honesty either way; beating the
  index in every window is NOT the adoption bar (nothing passive or active
  clears that bar honestly).

Arm A baselines are read from the committed
scripts/validate_rebalance_result.json rather than re-run.
"""

import json
import time

import pandas as pd

import app.portfolio as portfolio_module
from app.config import EXAMPLE_SYMBOLS
from app.data.providers import get_ohlcv

SYMBOLS = [entry["symbol"] for syms in EXAMPLE_SYMBOLS.values() for entry in syms]
PERIODS = [
    ("2004-07-30", "2004-2007 (virgen)"),
    ("2007-07-30", "2007-2010 (crisis)"),
    ("2010-07-30", "2010-2013 (virgen)"),
    ("2012-07-30", "2012-2015 (virgen)"),
    ("2014-07-30", "2014-2017"),
    ("2017-07-30", "2017-2020 (COVID)"),
    ("2019-07-30", "2019-2022"),
    ("2021-07-30", "2021-2024"),
    ("2023-07-30", "2023-2026"),
]
WARMUP_YEARS = 2
SIMULATED_YEARS = 3

if __name__ == "__main__":
    baseline_by_period = {
        r["period"]: r
        for r in json.load(open("scripts/validate_rebalance_result.json"))["results"]
    }

    t0 = time.time()
    all_results = []
    for start_date, label in PERIODS:
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

        sp500_return = None
        if "^GSPC" in dfs:
            sp = dfs["^GSPC"]
            sp_sim = sp[sp.index >= start_ts]["Close"]
            if len(sp_sim) > 1:
                sp500_return = round((float(sp_sim.iloc[-1]) / float(sp_sim.iloc[0]) - 1) * 100, 2)

        try:
            report = portfolio_module._run_simulation(
                dfs, start_date, None, 5, 10_000.0, None, False, 1, {},
                risk_regime_sizing=True,
                rebalance_months=3,
                equity_regime_tilt=True,
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

        base = baseline_by_period.get(label, {})
        risk_on_count = sum(1 for s in report["segments"] if s.get("equity_risk_on"))
        entry = {
            "period": label,
            "tilt_return_pct": report["total_return_pct"],
            "tilt_max_drawdown_pct": max_drawdown_pct,
            "baseline_return_pct": base.get("rebalanced_return_pct"),
            "baseline_max_drawdown_pct": base.get("rebalanced_max_drawdown_pct"),
            "return_delta_pp": round(report["total_return_pct"] - base["rebalanced_return_pct"], 2)
            if base else None,
            "sp500_return_pct": sp500_return,
            "vs_sp500_pp": round(report["total_return_pct"] - sp500_return, 2) if sp500_return is not None else None,
            "num_segments": len(report["segments"]),
            "num_risk_on_segments": risk_on_count,
            "segment_portfolios": [
                {"start": s["start_date"], "risk_on": s.get("equity_risk_on"), "portfolio": s["portfolio"]}
                for s in report["segments"]
            ],
        }
        all_results.append(entry)
        print(f"  TILT:     {entry['tilt_return_pct']}% (DD {max_drawdown_pct}%), {risk_on_count}/{entry['num_segments']} segmentos risk-on", flush=True)
        print(f"  BASELINE: {entry['baseline_return_pct']}% (DD {entry['baseline_max_drawdown_pct']}%) | delta: {entry['return_delta_pp']} pp", flush=True)
        print(f"  S&P 500:  {sp500_return}% | tilt vs S&P: {entry['vs_sp500_pp']} pp", flush=True)

    elapsed = time.time() - t0
    ran = [r for r in all_results if "skipped" not in r]
    beats_baseline = sum(1 for r in ran if r["return_delta_pp"] is not None and r["return_delta_pp"] > 0)
    beats_sp = sum(1 for r in ran if r["vs_sp500_pp"] is not None and r["vs_sp500_pp"] > 0)
    summary = {
        "elapsed_seconds": round(elapsed, 1),
        "num_periods_run": len(ran),
        "num_beats_baseline": beats_baseline,
        "num_beats_sp500": beats_sp,
        "results": all_results,
    }
    with open("scripts/validate_equity_tilt_result.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n=== RESUMEN: tilt le gana al default actual en {beats_baseline}/{len(ran)} ventanas y al S&P 500 en {beats_sp}/{len(ran)} ===", flush=True)
    print(f"elapsed_seconds={elapsed:.1f}", flush=True)
