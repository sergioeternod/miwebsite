"""Refresh both 12-month runs (current default with tilt, and the pre-tilt
model as comparison line) through the latest available bar, for the chart."""

import json

from app.portfolio import simulate_portfolio_real

if __name__ == "__main__":
    new = simulate_portfolio_real(start_date="2025-08-05", period="4y")
    with open("scripts/run_12m_sim_tilt_result.json", "w", encoding="utf-8") as f:
        json.dump(new, f, indent=2, ensure_ascii=False, default=str)
    print(f"NUEVO: {new['total_return_pct']}% hasta {new['end_date']}", flush=True)

    # El "modelo anterior" es el previo a ambos tilts: sin tilt accionario y
    # sin tilt de P/E (que hoy es default) — si no se apaga explícito, la
    # línea de comparación deja de ser el modelo que existió.
    old = simulate_portfolio_real(start_date="2025-08-05", period="4y", equity_regime_tilt=False, fundamental_pe_tilt=False)
    with open("scripts/run_12m_sim_result.json", "w", encoding="utf-8") as f:
        json.dump(old, f, indent=2, ensure_ascii=False, default=str)
    print(f"ANTERIOR (sin tilt): {old['total_return_pct']}% hasta {old['end_date']}", flush=True)
