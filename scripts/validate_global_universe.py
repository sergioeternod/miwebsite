"""Does adding international index markets (Nikkei, FTSE, DAX, Hang Seng)
to the universe improve the current default model?

This isn't a new parameter — it's more candidates for the same selection
logic. With the equity tilt active, risk-on segments now get to choose
among 7 index markets instead of 3 US ones, and the per-class cap (active
in defensive segments) still limits index concentration there.

Honest caveat baked into config.py: these indexes trade in local currency
and the simulator measures local-currency returns, with no FX conversion —
real-world access is via USD ETFs whose returns differ by the exchange
rate.

PRE-REGISTERED RULE, written before seeing any number:

- Arm B (current default model, extended universe) vs arm A (current
  default, US-only universe) across the 9 windows; arm A baselines from
  the committed scripts/validate_equity_tilt_result.json.
- ADOPT (keep the symbols in config) if arm B wins or ties a majority of
  the 9 windows and doesn't materially worsen the crisis windows. REVERT
  the config addition if it loses broadly — a bigger menu is only better
  if the selector actually picks well from it.
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
        intl = [s for s in ("^N225", "^FTSE", "^GDAXI", "^HSI") if s in dfs]
        print(f"  Universo: {len(dfs)} símbolos (internacionales disponibles: {intl})", flush=True)

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
        intl_picks = sorted({
            s for seg in report["segments"] for s in seg["portfolio"]
            if s in ("^N225", "^FTSE", "^GDAXI", "^HSI")
        })
        entry = {
            "period": label,
            "global_return_pct": report["total_return_pct"],
            "global_max_drawdown_pct": max_drawdown_pct,
            "baseline_return_pct": base.get("tilt_return_pct"),
            "baseline_max_drawdown_pct": base.get("tilt_max_drawdown_pct"),
            "return_delta_pp": round(report["total_return_pct"] - base["tilt_return_pct"], 2) if base else None,
            "drawdown_delta_pp": round(max_drawdown_pct - base["tilt_max_drawdown_pct"], 2) if base else None,
            "international_picks": intl_picks,
            "segment_portfolios": [{"start": s["start_date"], "portfolio": s["portfolio"]} for s in report["segments"]],
        }
        all_results.append(entry)
        print(f"  GLOBAL:   {entry['global_return_pct']}% (DD {max_drawdown_pct}%) | eligió internacionales: {intl_picks or 'ninguno'}", flush=True)
        print(f"  BASELINE: {entry['baseline_return_pct']}% (DD {entry['baseline_max_drawdown_pct']}%) | delta: {entry['return_delta_pp']} pp", flush=True)

    elapsed = time.time() - t0
    ran = [r for r in all_results if "skipped" not in r]
    wins_or_ties = sum(1 for r in ran if r["return_delta_pp"] is not None and r["return_delta_pp"] >= 0)
    beats = sum(1 for r in ran if r["return_delta_pp"] is not None and r["return_delta_pp"] > 0)
    summary = {
        "elapsed_seconds": round(elapsed, 1),
        "num_periods_run": len(ran),
        "num_beats_baseline": beats,
        "num_wins_or_ties": wins_or_ties,
        "results": all_results,
    }
    with open("scripts/validate_global_universe_result.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n=== RESUMEN: universo global gana en {beats}/{len(ran)} y gana-o-empata en {wins_or_ties}/{len(ran)} ventanas ===", flush=True)
    print(f"elapsed_seconds={elapsed:.1f}", flush=True)
