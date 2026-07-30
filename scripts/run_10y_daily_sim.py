"""One-off script: 10-year, daily-recalculation portfolio simulation on a
custom synthetic scenario (real data is unreachable from this sandbox's
network policy — Yahoo Finance connections are blocked).

Builds 5 profiles with ~3 years of synthetic warmup followed by ~10 years
(3650 days) of multiple distinct regimes each, then runs the exact same
walk-forward portfolio simulator used elsewhere in the app, with step=1
(recalculates the ensemble every single day) and adaptive learning on
(the default).
"""

import json
import time

from app.data.synthetic import generate_ohlcv
from app.portfolio import _run_simulation

_SYNTHETIC_START_DATE = "2013-07-30"
_WARMUP_DAYS = 1096  # ~3 years; lands right around 2016-07-30
_START_DATE = "2016-07-30"  # 10 years before "today" (2026-07-30) in this scenario

PROFILES_10Y = [
    {
        "label": "Símbolo A (alcista con correcciones)",
        "regimes": [
            {"name": "historial previo", "days": _WARMUP_DAYS, "drift": 0.0006, "volatility": 0.013},
            {"name": "alza larga", "days": 1500, "drift": 0.0012, "volatility": 0.013},
            {"name": "corrección", "days": 250, "drift": -0.0025, "volatility": 0.02},
            {"name": "recuperación y nueva alza", "days": 1900, "drift": 0.0010, "volatility": 0.014},
        ],
    },
    {
        "label": "Símbolo B (bajista prolongada con rebotes)",
        "regimes": [
            {"name": "historial previo", "days": _WARMUP_DAYS, "drift": 0.0004, "volatility": 0.014},
            {"name": "baja prolongada", "days": 1200, "drift": -0.0012, "volatility": 0.016},
            {"name": "rebote", "days": 400, "drift": 0.0018, "volatility": 0.015},
            {"name": "nueva baja", "days": 1200, "drift": -0.0010, "volatility": 0.017},
            {"name": "lateral final", "days": 850, "drift": 0.0001, "volatility": 0.012},
        ],
    },
    {
        "label": "Símbolo C (lateral con ciclos)",
        "regimes": [
            {"name": "historial previo", "days": _WARMUP_DAYS, "drift": 0.0005, "volatility": 0.012},
            {"name": "lateral 1", "days": 1200, "drift": 0.0001, "volatility": 0.009},
            {"name": "repunte", "days": 600, "drift": 0.0015, "volatility": 0.013},
            {"name": "lateral 2", "days": 1200, "drift": -0.0001, "volatility": 0.010},
            {"name": "caída", "days": 650, "drift": -0.0020, "volatility": 0.018},
        ],
    },
    {
        "label": "Símbolo D (volátil sin tendencia clara)",
        "regimes": [
            {"name": "historial previo", "days": _WARMUP_DAYS, "drift": 0.0005, "volatility": 0.013},
            {"name": "volátil alza", "days": 1000, "drift": 0.0006, "volatility": 0.028},
            {"name": "volátil baja", "days": 900, "drift": -0.0008, "volatility": 0.030},
            {"name": "volátil lateral", "days": 1750, "drift": 0.0002, "volatility": 0.025},
        ],
    },
    {
        "label": "Símbolo E (mixto multi-ciclo)",
        "regimes": [
            {"name": "historial previo", "days": _WARMUP_DAYS, "drift": 0.0005, "volatility": 0.013},
            {"name": "corrección", "days": 300, "drift": -0.003, "volatility": 0.02},
            {"name": "recuperación", "days": 600, "drift": 0.0022, "volatility": 0.015},
            {"name": "alza madura", "days": 900, "drift": 0.0008, "volatility": 0.012},
            {"name": "corrección 2", "days": 350, "drift": -0.0025, "volatility": 0.022},
            {"name": "recuperación 2", "days": 700, "drift": 0.0018, "volatility": 0.016},
            {"name": "lateral final", "days": 800, "drift": 0.0002, "volatility": 0.011},
        ],
    },
]

if __name__ == "__main__":
    t0 = time.time()
    dfs = {
        profile["label"]: generate_ohlcv(regimes=profile["regimes"], start_date=_SYNTHETIC_START_DATE, seed=42)
        for profile in PROFILES_10Y
    }
    report = _run_simulation(
        dfs,
        start_date=_START_DATE,
        end_date=None,
        portfolio_size=5,
        initial_capital=10_000.0,
        commission_bps=None,
        allow_short=True,
        step=1,
        errors={},
        min_confidence_pct=55.0,
        adaptive_learning=True,
    )
    elapsed = time.time() - t0

    with open("/home/user/miwebsite/scripts/sim_10y_result.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)

    print(f"elapsed_seconds={elapsed:.1f}")
    print(f"start_date={report['start_date']} end_date={report['end_date']} num_trading_days={report['num_trading_days']}")
    print(f"initial_capital={report['initial_capital']} final_equity={report['final_equity']}")
    print(f"total_pnl_amount={report['total_pnl_amount']} total_return_pct={report['total_return_pct']}")
    print("portfolio:", report["portfolio"])
    print("hindsight_summary:", report["hindsight_summary"])
    for p in report["per_symbol"]:
        print(
            f"  {p['symbol']}: final_equity={p['final_equity']} pnl={p['pnl_amount']} "
            f"num_trades={p['metrics']['num_trades']} win_rate={p['metrics']['win_rate_pct']} "
            f"hindsight={p['hindsight_summary']}"
        )
    if report["errors"]:
        print("errors:", report["errors"])
