"""Second, pre-registered attempt at the emergency boundary: hysteresis +
multi-day confirmation.

The raw-cross variant was validated and REJECTED (2/9 on returns; 6-14
cuts per 3-year window — see validate_emergency_result.json). Its autopsy
said the mechanism repaired the target windows (2008: +23 pp, 2023-2026:
+36.6 pp) but the whipsaw of false alarms ate 13-79 pp everywhere else.
This variant attacks exactly the false alarms: a flip only counts after
EMERGENCY_CONFIRM_DAYS (5) consecutive closes beyond an
EMERGENCY_HYSTERESIS_BAND_PCT (2%) margin past the 200-day moving average.
Both values were fixed from standard practice BEFORE running this — they
are not swept, and if this variant fails it is not iterated further on
these windows.

PRE-REGISTERED RULE (same as v1): adopt only if it beats the current
default in a majority of the 9 windows without breaking the ones that
work; the cut counts are reported to verify the mechanism (they should
drop from 6-14 to a small handful — if they don't, the premise was wrong
regardless of returns).
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
        for r in json.load(open("scripts/validate_equity_tilt_result.json"))["results"]
    }
    v1_by_period = {
        r["period"]: r
        for r in json.load(open("scripts/validate_emergency_result.json"))["results"]
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

        try:
            report = portfolio_module._run_simulation(
                dfs, start_date, None, 5, 10_000.0, None, False, 1, {},
                risk_regime_sizing=True,
                rebalance_months=3,
                equity_regime_tilt=True,
                emergency_reselect=True,
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
        v1 = v1_by_period.get(label, {})
        cuts = [s for s in report["segments"] if "emergency_cut_date" in s]
        entry = {
            "period": label,
            "v2_return_pct": report["total_return_pct"],
            "v2_max_drawdown_pct": max_drawdown_pct,
            "baseline_return_pct": base.get("tilt_return_pct"),
            "baseline_max_drawdown_pct": base.get("tilt_max_drawdown_pct"),
            "return_delta_pp": round(report["total_return_pct"] - base["tilt_return_pct"], 2) if base else None,
            "drawdown_delta_pp": round(max_drawdown_pct - base["tilt_max_drawdown_pct"], 2) if base else None,
            "v1_raw_cuts": v1.get("num_emergency_cuts"),
            "v2_cuts": len(cuts),
            "emergency_cuts": [
                {"segment_start": s["start_date"], "cut_date": s["emergency_cut_date"], "reason": s["cut_reason"]}
                for s in cuts
            ],
        }
        all_results.append(entry)
        print(f"  V2 (banda 2% + 5 días): {entry['v2_return_pct']}% (DD {max_drawdown_pct}%), {len(cuts)} cortes (v1 cruda: {entry['v1_raw_cuts']})", flush=True)
        print(f"  BASELINE (default):     {entry['baseline_return_pct']}% (DD {entry['baseline_max_drawdown_pct']}%) | delta retorno: {entry['return_delta_pp']} pp | delta DD: {entry['drawdown_delta_pp']} pp", flush=True)

    elapsed = time.time() - t0
    ran = [r for r in all_results if "skipped" not in r]
    beats_return = sum(1 for r in ran if r["return_delta_pp"] is not None and r["return_delta_pp"] > 0)
    smaller_dd = sum(1 for r in ran if r["drawdown_delta_pp"] is not None and r["drawdown_delta_pp"] > 0)
    summary = {
        "elapsed_seconds": round(elapsed, 1),
        "hysteresis_band_pct": portfolio_module.EMERGENCY_HYSTERESIS_BAND_PCT,
        "confirm_days": portfolio_module.EMERGENCY_CONFIRM_DAYS,
        "num_periods_run": len(ran),
        "num_beats_baseline_return": beats_return,
        "num_smaller_drawdown": smaller_dd,
        "total_v2_cuts": sum(r["v2_cuts"] for r in ran),
        "total_v1_cuts": sum(r["v1_raw_cuts"] or 0 for r in ran),
        "results": all_results,
    }
    with open("scripts/validate_emergency_v2_result.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n=== RESUMEN: v2 mejora retorno en {beats_return}/{len(ran)} y drawdown en {smaller_dd}/{len(ran)}; cortes totales {summary['total_v2_cuts']} (v1: {summary['total_v1_cuts']}) ===", flush=True)
    print(f"elapsed_seconds={elapsed:.1f}", flush=True)
