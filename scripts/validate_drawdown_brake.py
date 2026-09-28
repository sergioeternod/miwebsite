"""Does a portfolio-level drawdown brake improve the current default model?

Motivation: the model's documented blind spot is fast corrections while the
S&P is still above its 200-day SMA (e.g. Mar/Jun 2026). Tested-and-rejected
fixes (emergency reselect v1/v2, monthly rebalance, position cap) all acted
on SELECTION. This one acts on SIZING: when the portfolio's own equity is
deep under its running peak, scale every position down; restore when it
recovers. It is causal (the decision at day t's close, using only equity up
to t, scales day t+1's return) and computable as an overlay on the default
model's equity curve, so both arms share identical underlying data.

THE RULE (primary config): exposure drops to 50% when equity closes >=6%
below its running peak; restores to 100% when equity recovers to within 3%
of that peak. The braked curve's own peak is the reference (the investor's
actual equity). Brake flips are assumed commission-free — disclosed
simplification; flips are infrequent and fractional scaling matches the
risk-parity assumption already in the engine.

A robustness grid (trigger 4/6/8%, release = trigger/2, exposure 50%) is
declared here IN ADVANCE and reported for information only.

PRE-REGISTERED ADOPTION RULE, written before seeing any number, decided
ONLY on the primary config (6% / 3% / 50%): ADOPT drawdown_brake as default
only if ALL of
  (a) max drawdown improves (shrinks) in >= 7 of the 9 windows,
  (b) average max-drawdown improvement is >= +2.0 pp, and
  (c) average total-return delta is >= -1.0 pp
      (protection may cost at most 1 pp per window on average).
If it protects but costs more than that, it's an expensive hedge: REJECT.
If it doesn't protect consistently, it's noise: REJECT.
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
PRIMARY = (0.06, 0.03, 0.5)  # trigger, release, braked exposure
GRID = [(0.04, 0.02, 0.5), (0.06, 0.03, 0.5), (0.08, 0.04, 0.5)]


def apply_brake(curve: pd.Series, trigger: float, release: float, braked_exposure: float) -> pd.Series:
    """Causal overlay: day t's close decides day t+1's exposure."""
    returns = curve.pct_change().fillna(0.0)
    equity = float(curve.iloc[0])
    peak = equity
    exposure = 1.0
    out = [equity]
    for r in returns.iloc[1:]:
        equity *= 1 + exposure * float(r)
        out.append(equity)
        peak = max(peak, equity)
        dd = equity / peak - 1
        if exposure == 1.0 and dd <= -trigger:
            exposure = braked_exposure
        elif exposure < 1.0 and dd >= -release:
            exposure = 1.0
    return pd.Series(out, index=curve.index)


def metrics(curve: pd.Series) -> tuple[float, float]:
    ret = round((float(curve.iloc[-1]) / float(curve.iloc[0]) - 1) * 100, 2)
    dd = round(float(((curve - curve.cummax()) / curve.cummax()).min()) * 100, 2)
    return ret, dd


if __name__ == "__main__":
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
            )
        except ValueError as exc:
            print(f"  Omitido: {exc}", flush=True)
            all_results.append({"period": label, "skipped": str(exc)})
            continue

        curve = pd.Series(
            [p["equity"] for p in report["portfolio_equity_curve"]],
            index=[p["date"] for p in report["portfolio_equity_curve"]],
        )
        base_ret, base_dd = metrics(curve)

        entry = {"period": label, "baseline_return_pct": base_ret, "baseline_max_drawdown_pct": base_dd, "grid": {}}
        for trigger, release, expo in GRID:
            braked = apply_brake(curve, trigger, release, expo)
            b_ret, b_dd = metrics(braked)
            key = f"{int(trigger*100)}/{int(release*100)}/{int(expo*100)}"
            entry["grid"][key] = {
                "return_pct": b_ret, "max_drawdown_pct": b_dd,
                "return_delta_pp": round(b_ret - base_ret, 2),
                "drawdown_improvement_pp": round(base_dd - b_dd, 2),  # positivo = drawdown más chico
            }
            if (trigger, release, expo) == PRIMARY:
                entry.update({
                    "brake_return_pct": b_ret, "brake_max_drawdown_pct": b_dd,
                    "return_delta_pp": entry["grid"][key]["return_delta_pp"],
                    "drawdown_improvement_pp": entry["grid"][key]["drawdown_improvement_pp"],
                })
        all_results.append(entry)
        print(f"  BASE:  {base_ret}% (DD {base_dd}%)", flush=True)
        print(f"  FRENO: {entry['brake_return_pct']}% (DD {entry['brake_max_drawdown_pct']}%) | "
              f"delta ret {entry['return_delta_pp']} pp | mejora DD {entry['drawdown_improvement_pp']} pp", flush=True)

    elapsed = time.time() - t0
    ran = [r for r in all_results if "skipped" not in r]
    dd_wins = sum(1 for r in ran if r["drawdown_improvement_pp"] > 0)
    avg_dd_impr = round(sum(r["drawdown_improvement_pp"] for r in ran) / len(ran), 2) if ran else None
    avg_ret_delta = round(sum(r["return_delta_pp"] for r in ran) / len(ran), 2) if ran else None
    adopted = bool(ran) and dd_wins >= 7 and avg_dd_impr >= 2.0 and avg_ret_delta >= -1.0
    summary = {
        "elapsed_seconds": round(elapsed, 1),
        "num_periods_run": len(ran),
        "primary_config": "trigger 6% / release 3% / exposure 50%",
        "dd_improvement_windows": dd_wins,
        "avg_drawdown_improvement_pp": avg_dd_impr,
        "avg_return_delta_pp": avg_ret_delta,
        "adopted_per_prereg_rule": adopted,
        "results": all_results,
    }
    with open("scripts/validate_drawdown_brake_result.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, default=str)
    print(f"\n=== RESUMEN (config primaria): DD mejora en {dd_wins}/{len(ran)} ventanas, "
          f"mejora DD promedio {avg_dd_impr} pp, delta retorno promedio {avg_ret_delta} pp ===", flush=True)
    print(f"=== REGLA PRE-REGISTRADA → {'ADOPTAR' if adopted else 'RECHAZAR'} ===", flush=True)
    print(f"elapsed_seconds={elapsed:.1f}", flush=True)
