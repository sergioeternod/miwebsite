"""Last-12-months run of the NEW default model (long-only, risk-regime,
quarterly re-selection + equity-regime tilt) for the updated 12-month chart.
The pre-tilt run is committed in run_12m_sim_result.json and stays as the
'modelo anterior' comparison line."""

import json

from app.portfolio import simulate_portfolio_real

if __name__ == "__main__":
    report = simulate_portfolio_real(
        start_date="2025-08-05",
        period="4y",
    )
    with open("scripts/run_12m_sim_tilt_result.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    print(f"retorno: {report['total_return_pct']}% | benchmark canasta: {report['benchmark_buy_hold']['total_return_pct']}%")
    print(f"segmentos: {[(s['start_date'], s.get('equity_risk_on'), s['portfolio']) for s in report['segments']]}")
