"""Last-12-months run of the current default model (long-only, risk-regime
sizing, quarterly re-selection) for the 12-month profit chart."""

import json

from app.portfolio import simulate_portfolio_real

if __name__ == "__main__":
    report = simulate_portfolio_real(
        start_date="2025-08-05",
        period="4y",  # ~2y warmup before the simulated year, plus margin
    )
    with open("scripts/run_12m_sim_result.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    print(f"portfolio inicial: {[c['symbol'] for c in report['portfolio']]}")
    print(f"retorno: {report['total_return_pct']}% | benchmark: {report['benchmark_buy_hold']['total_return_pct']}% | vs: {report['vs_benchmark_pct_points']} pp")
    print(f"segmentos: {[(s['start_date'], s['portfolio']) for s in report['segments']]}")
