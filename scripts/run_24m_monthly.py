"""Last-24-months run of the current default model (long-only + full risk
stack), broken down into month-by-month portfolio returns, each with its
annualized equivalent."""

import json

import pandas as pd

from app.portfolio import simulate_portfolio_real

START_DATE = "2024-08-04"  # 24 months before today (2026-08-04)

report = simulate_portfolio_real(start_date=START_DATE, period="4y", portfolio_size=5, step=1)

curve = pd.Series(
    {pd.Timestamp(p["date"]): p["equity"] for p in report["portfolio_equity_curve"]}
).sort_index()
monthly = curve.resample("ME").last()
monthly_returns = monthly.pct_change().dropna()

rows = []
for date, r in monthly_returns.items():
    rows.append(
        {
            "mes": date.strftime("%Y-%m"),
            "retorno_mensual_pct": round(r * 100, 2),
            "equivalente_anualizado_pct": round(((1 + r) ** 12 - 1) * 100, 2),
        }
    )

out = {
    "start_date": report["start_date"],
    "end_date": report["end_date"],
    "portfolio": [
        {"symbol": c["symbol"], "action": c["action_at_selection"], "confianza": c["confidence_pct_at_selection"]}
        for c in report["portfolio"]
    ],
    "total_return_pct": report["total_return_pct"],
    "benchmark_buy_hold_return_pct": report["benchmark_buy_hold"]["total_return_pct"],
    "vs_benchmark_pct_points": report["vs_benchmark_pct_points"],
    "monthly": rows,
}
with open("scripts/run_24m_monthly_result.json", "w", encoding="utf-8") as f:
    json.dump(out, f, indent=2, ensure_ascii=False)
print(json.dumps(out, indent=2, ensure_ascii=False))
