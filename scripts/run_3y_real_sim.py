"""Portfolio simulation over real market data for (approximately) the last
3 years, with daily ensemble recalculation (step=1) and a daily P&L series
ready for charting.

The window targets 3 years before "today", but the validated pipeline
requires a valid BUY >=55% selection on the start date; when the target
date has none (e.g. a correction trough), we probe forward week by week
and start at the first date with a valid book, reporting that date
honestly in the output. Requires network access to Yahoo Finance
(see app/data/providers.py for the fallback chain)."""

import os
os.environ.setdefault("MIWEB_PRICE_VINTAGE", "1")  # historial anclado a la añada (app/data/vintage.py)

import json
import time

import pandas as pd

from app.portfolio import simulate_portfolio_real

# Ancla el inicio a la malla trimestral (5 feb/may/ago/nov): el último nodo
# que quede a >=3 años de hoy. Una ventana rodante pura mueve las fronteras
# de re-selección día con día y el retorno salta decenas de puntos por un
# solo día de corrimiento (p.ej. +47% -> +167% al capturar o no un trimestre
# 100% TSLA); anclada, la serie publicada es estable entre días.
_hoy = pd.Timestamp.today().normalize()
_grid = [pd.Timestamp(year=y, month=m, day=5) for y in range(_hoy.year - 4, _hoy.year + 1) for m in (2, 5, 8, 11)]
TARGET_START = str(max(d for d in _grid if d <= _hoy - pd.DateOffset(years=3)).date())
MAX_PROBE_WEEKS = 12
PERIOD = "5y"  # ~2y of warmup before the start + the ~3y simulated window

if __name__ == "__main__":
    t0 = time.time()
    report = None
    start = pd.Timestamp(TARGET_START)
    for _ in range(MAX_PROBE_WEEKS):
        try:
            report = simulate_portfolio_real(
                start_date=str(start.date()),
                period=PERIOD,
                portfolio_size=5,
                step=1,
            )
            break
        except ValueError as exc:
            if "No se encontraron símbolos" not in str(exc):
                raise
            print(f"sin selección válida el {start.date()}, probando la semana siguiente")
            start += pd.Timedelta(days=7)
    if report is None:
        raise SystemExit(f"Sin selección válida en {MAX_PROBE_WEEKS} semanas desde {TARGET_START}.")
    elapsed = time.time() - t0

    with open("scripts/sim_3y_real_result.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)

    print(f"elapsed_seconds={elapsed:.1f}")
    print(f"start_date={report['start_date']} end_date={report['end_date']} num_trading_days={report['num_trading_days']}")
    print(f"initial_capital={report['initial_capital']} final_equity={report['final_equity']}")
    print(f"total_pnl_amount={report['total_pnl_amount']} total_return_pct={report['total_return_pct']}")
    print("portfolio:", report["portfolio"])
    print("hindsight_summary:", report["hindsight_summary"])
    for seg in report["segments"]:
        port = seg.get("portfolio")
        syms = [p["symbol"] for p in port] if port and isinstance(port[0], dict) else port
        print(f"  {seg['start_date']}: capital_start={seg['capital_start']} portfolio={syms or 'efectivo'}")
    bench = report["benchmark_buy_hold"]
    print(f"benchmark_buy_hold: return={bench['total_return_pct']}% | vs_benchmark_pct_points={report['vs_benchmark_pct_points']}")
    if report["errors"]:
        print("errors:", report["errors"])
