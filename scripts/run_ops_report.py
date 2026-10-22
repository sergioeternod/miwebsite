"""Re-runs the 9 historical validation windows (2004-2026) with the
current default model, capturing every quarterly operation (the selected
portfolio per segment) instead of only aggregate metrics. Output feeds
the 22-year operations report page.

Same windows, data fetch and model invocation as the validators
(see validate_drawdown_brake.py); writes scripts/ops_report_result.json.
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


def metrics(curve: pd.Series) -> tuple[float, float]:
    ret = round((float(curve.iloc[-1]) / float(curve.iloc[0]) - 1) * 100, 2)
    dd = round(float(((curve - curve.cummax()) / curve.cummax()).min()) * 100, 2)
    return ret, dd


if __name__ == "__main__":
    t0 = time.time()
    windows = []
    for start_date, label in PERIODS:
        print(f"=== {label} ===", flush=True)
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
            )
        except ValueError as exc:
            print(f"  omitido: {exc}", flush=True)
            windows.append({"period": label, "skipped": str(exc)})
            continue

        curve = pd.Series(
            [p["equity"] for p in report["portfolio_equity_curve"]],
            index=[p["date"] for p in report["portfolio_equity_curve"]],
        )
        ret, dd = metrics(curve)

        spx = dfs.get("^GSPC")
        sp_ret = None
        if spx is not None:
            s = spx["Close"].loc[report["start_date"][:10]:report["end_date"][:10]]
            if len(s) > 1:
                sp_ret = round((float(s.iloc[-1]) / float(s.iloc[0]) - 1) * 100, 2)

        segs_raw = report["segments"]
        caps = [s["capital_start"] for s in segs_raw] + [report["final_equity"]]
        segments = []
        for i, s in enumerate(segs_raw):
            port = s.get("portfolio")
            syms = [p["symbol"] for p in port] if port and isinstance(port[0], dict) else (port or [])
            segments.append({
                "date": str(s["start_date"])[:10],
                "portfolio": syms,
                "ret": round((caps[i + 1] / caps[i] - 1) * 100, 2) if caps[i] else 0.0,
                "risk_on": s.get("equity_risk_on"),
            })

        windows.append({
            "period": label,
            "start": str(report["start_date"])[:10],
            "end": str(report["end_date"])[:10],
            "return_pct": ret,
            "max_drawdown_pct": dd,
            "sp500_return_pct": sp_ret,
            "final_equity": report["final_equity"],
            "segments": segments,
        })
        print(f"  ret {ret}% dd {dd}% sp {sp_ret}% segmentos {len(segments)}", flush=True)

    out = {"elapsed_seconds": round(time.time() - t0, 1), "windows": windows}
    with open("scripts/ops_report_result.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False, default=str)
    ran = [w for w in windows if "skipped" not in w]
    print(f"listo: {len(ran)}/{len(windows)} ventanas, {sum(len(w['segments']) for w in ran)} segmentos, "
          f"{out['elapsed_seconds']}s", flush=True)
