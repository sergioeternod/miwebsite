"""Hipótesis 7: ¿filtrar los BUY respaldados por sma_crossover (exigiendo que
trend_confirmation también esté largo) mejora el default actual?

Mecanismo, brazos y REGLA DE DECISIÓN pre-registrados en
scripts/validate_sma_confirmation_PREREG.md, commiteado antes de correr esto.

Brazo A (baseline, sin re-correr): pe_tilt_return_pct del comiteado
scripts/validate_pe_tilt_result.json — el default actual completo.
Brazo B: default actual + sma_buy_confirmation=True.
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
        for r in json.load(open("scripts/validate_pe_tilt_result.json"))["results"]
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
                fundamental_pe_tilt=True,
                sma_buy_confirmation=True,
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
        entry = {
            "period": label,
            "confirm_return_pct": report["total_return_pct"],
            "confirm_max_drawdown_pct": max_drawdown_pct,
            "baseline_return_pct": base.get("pe_tilt_return_pct"),
            "baseline_max_drawdown_pct": base.get("pe_tilt_max_drawdown_pct"),
            "return_delta_pp": round(report["total_return_pct"] - base["pe_tilt_return_pct"], 2)
            if base else None,
            "num_segments": len(report["segments"]),
            "segment_portfolios": [
                {"start": s["start_date"], "risk_on": s.get("equity_risk_on"), "portfolio": s["portfolio"]}
                for s in report["segments"]
            ],
        }
        all_results.append(entry)
        print(f"  CONFIRM:  {entry['confirm_return_pct']}% (DD {max_drawdown_pct}%)", flush=True)
        print(f"  BASELINE: {entry['baseline_return_pct']}% (DD {entry['baseline_max_drawdown_pct']}%) | delta: {entry['return_delta_pp']} pp", flush=True)

    elapsed = time.time() - t0
    ran = [r for r in all_results if "skipped" not in r]
    affected = [r for r in ran if r["return_delta_pp"] is not None and abs(r["return_delta_pp"]) > 0.01]
    improved = sum(1 for r in affected if r["return_delta_pp"] > 0)
    worsened = sum(1 for r in affected if r["return_delta_pp"] < 0)
    mean_delta = round(sum(r["return_delta_pp"] for r in ran if r["return_delta_pp"] is not None) / max(len(ran), 1), 2)
    crisis = {r["period"]: r["return_delta_pp"] for r in ran if "crisis" in r["period"] or "COVID" in r["period"]}
    crisis_ok = all(d is None or d >= -10 for d in crisis.values())

    # Regla pre-registrada (las cuatro):
    adopt = (
        len(affected) >= 2
        and improved > worsened
        and mean_delta > 0
        and crisis_ok
    )
    summary = {
        "elapsed_seconds": round(elapsed, 1),
        "num_periods_run": len(ran),
        "num_affected": len(affected),
        "num_improved": improved,
        "num_worsened": worsened,
        "mean_delta_pp": mean_delta,
        "crisis_deltas_pp": crisis,
        "crisis_guard_ok": crisis_ok,
        "preregistered_decision": "ADOPT" if adopt else "REJECT",
        "results": all_results,
    }
    with open("scripts/validate_sma_confirmation_result.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n=== RESUMEN: {len(affected)} ventanas afectadas, {improved} mejoran / {worsened} empeoran, "
          f"delta medio {mean_delta} pp, guardia de crisis {'OK' if crisis_ok else 'FALLA'} "
          f"=> {summary['preregistered_decision']} ===", flush=True)
    print(f"elapsed_seconds={elapsed:.1f}", flush=True)
