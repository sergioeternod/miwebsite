"""Does capping any single position at 40% of capital (surplus in cash)
improve the current default model?

Motivation (measured): with few candidates clearing the confidence bar,
nothing stops full concentration — the frozen 2004-2007 run held 100% AAPL,
and the week of 2026-08-03 held 100% ^DJI. The cap reads "only one symbol
convinces me" as thin portfolio-level conviction and bounds single-name
risk; it also tames extreme risk-parity weights on low-volatility
instruments. The benchmark arm holds the same idle cash, so the comparison
isolates the cap's effect.

The 0.4 value is fixed from standard concentration-limit practice BEFORE
running — not swept. (With a 5-slot portfolio it only binds when conviction
is thin or a weight is extreme: 2.5x the equal-weight share.)

PRE-REGISTERED RULE, written before seeing any number: this is an
insurance feature, judged like the risk-regime was — ADOPT if it reduces
max drawdown in a clear majority of the 9 windows AND its average return
cost is small (>-5 pp avg would reject it); otherwise keep it off. A cap
whose only effect is capping the lucky wins (2004-2007 style) without
drawdown benefit elsewhere is a cost, not insurance.
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
CAP = 0.4

if __name__ == "__main__":
    baseline_by_period = {
        r["period"]: r
        for r in json.load(open("scripts/validate_equity_tilt_result.json"))["results"]
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
                max_position_weight=CAP,
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
        cash_segments = sum(1 for s in report["segments"] if s.get("cash_reserved", 0) > 1)
        entry = {
            "period": label,
            "capped_return_pct": report["total_return_pct"],
            "capped_max_drawdown_pct": max_drawdown_pct,
            "baseline_return_pct": base.get("tilt_return_pct"),
            "baseline_max_drawdown_pct": base.get("tilt_max_drawdown_pct"),
            "return_delta_pp": round(report["total_return_pct"] - base["tilt_return_pct"], 2) if base else None,
            "drawdown_delta_pp": round(max_drawdown_pct - base["tilt_max_drawdown_pct"], 2) if base else None,
            "num_segments_with_cash": cash_segments,
            "num_segments": len(report["segments"]),
        }
        all_results.append(entry)
        print(f"  CAP 40%:  {entry['capped_return_pct']}% (DD {max_drawdown_pct}%), efectivo en {cash_segments}/{entry['num_segments']} segmentos", flush=True)
        print(f"  BASELINE: {entry['baseline_return_pct']}% (DD {entry['baseline_max_drawdown_pct']}%) | delta retorno: {entry['return_delta_pp']} pp | delta DD: {entry['drawdown_delta_pp']} pp", flush=True)

    elapsed = time.time() - t0
    ran = [r for r in all_results if "skipped" not in r]
    smaller_dd = sum(1 for r in ran if r["drawdown_delta_pp"] is not None and r["drawdown_delta_pp"] > 0)
    beats = sum(1 for r in ran if r["return_delta_pp"] is not None and r["return_delta_pp"] > 0)
    avg_ret = round(sum(r["return_delta_pp"] for r in ran) / len(ran), 2) if ran else None
    summary = {
        "elapsed_seconds": round(elapsed, 1),
        "max_position_weight": CAP,
        "num_periods_run": len(ran),
        "num_smaller_drawdown": smaller_dd,
        "num_beats_baseline_return": beats,
        "avg_return_delta_pp": avg_ret,
        "results": all_results,
    }
    with open("scripts/validate_position_cap_result.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n=== RESUMEN: cap 40% reduce drawdown en {smaller_dd}/{len(ran)} y mejora retorno en {beats}/{len(ran)} (delta promedio {avg_ret} pp) ===", flush=True)
    print(f"elapsed_seconds={elapsed:.1f}", flush=True)
