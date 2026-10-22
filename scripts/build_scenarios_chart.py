"""Builds the best/worst-scenario page (Mejor y peor escenario) from the
stored 9-window validation results.

Reads scripts/validate_equity_tilt_result.json (per-window model return,
max drawdown and S&P 500 return — the run that validated the current
default model) and scripts/sim_3y_real_result.json (the daily 3-year sim,
for the cross-reference line in the worst-window anatomy). No simulation
runs here; the page only changes when those inputs do, plus the date
stamp. Runs after run_3y_real_sim.py in the daily cycle.

Usage: build_scenarios_chart.py OUT_HTML
"""

import json
import sys
from datetime import date

TEMPLATE = "scripts/templates/scenarios_template.html"
TILT_JSON = "scripts/validate_equity_tilt_result.json"
SIM3Y_JSON = "scripts/sim_3y_real_result.json"
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
TAGS = {"crisis": "crisis 2008", "COVID": "COVID"}


def pct(v: float) -> str:
    return f"{'+' if v >= 0 else '−'}{abs(v):.1f}"


if __name__ == "__main__":
    out_path = sys.argv[1] if len(sys.argv) > 1 else "scenarios.html"
    tilt = json.load(open(TILT_JSON))
    hoy = date.today()

    windows = []
    for r in tilt["results"]:
        years = r["period"].split(" ")[0]          # "2004-2007"
        y0, y1 = years.split("-")
        tag = next((v for k, v in TAGS.items() if k in r["period"]), None)
        windows.append({
            "p": f"{y0}-{y1[2:]}",
            "model": r["tilt_return_pct"],
            "sp": r["sp500_return_pct"],
            "pp": round(r["vs_sp500_pp"], 1),
            "dd": r["tilt_max_drawdown_pct"],
            "recent": int(y1) >= hoy.year - 5,
            "tag": tag,
        })

    best = max(windows, key=lambda w: w["pp"])
    worst = min(windows, key=lambda w: w["pp"])
    worst["tag"] = "la derrota" if worst["pp"] < 0 else worst["tag"]
    worst_dd_w = min(windows, key=lambda w: w["dd"])
    worst_close_w = min(windows, key=lambda w: w["model"])
    data = {
        "windows": windows,
        "wins": sum(1 for w in windows if w["pp"] > 0),
        "best": best,
        "worst": worst,
        "worst_dd": worst_dd_w["dd"],
        "worst_dd_p": worst_dd_w["p"],
        "worst_close": worst_close_w["model"],
        "worst_close_p": worst_close_w["p"],
    }

    desc_best = (f"La otra cara: en {best['p']} el modelo hizo {pct(best['model'])}% contra "
                 f"{pct(best['sp'])}% del índice — {pct(best['pp'])} pp de ventaja, con un drawdown máximo "
                 f"de {best['dd']:.1f}%. Un mercado de tendencias sostenidas es el terreno donde la rotación "
                 f"trimestral del modelo más paga: monta la tendencia y suelta al rezagado.")

    try:
        sim = json.load(open(SIM3Y_JSON))
        sim_line = (f" Mismo patrón que muestra la simulación de 3 años publicada: "
                    f"{pct(sim['total_return_pct'])}% del modelo contra "
                    f"{pct(sim['benchmark_buy_hold']['total_return_pct'])}% de no haber tocado su primera selección.")
    except Exception:
        sim_line = ""
    desc_worst = (f"El trienio {worst['p']} lo dominó un rally concentrado en pocas acciones (NVDA sobre "
                  f"todo). El modelo, que rota trimestralmente, se bajó demasiado pronto; quedarse sentado "
                  f"en el índice pagó más ({pct(worst['model'])}% vs {pct(worst['sp'])}%).{sim_line}")

    note = (f"el peor escenario histórico reciente no fue perder dinero al final — fue ganar mucho menos "
            f"que el índice ({pct(worst['model'])}% vs {pct(worst['sp'])}%) y ver el capital "
            f"{abs(worst['dd']):.0f}% abajo del pico a medio camino. El mejor y el peor trienio salen del "
            f"mismo modelo con las mismas reglas: la diferencia la puso el mercado que le tocó. Esa ventana "
            f"mala además es ruidosa entre corridas (una trayectoria llegó a verse en −7.85% antes de anclar "
            f"los datos); la evidencia estable es el promedio de las 9 ventanas, y el libro real en papel "
            f"la está midiendo fuera de muestra. Simulación histórica; no es asesoría financiera ni "
            f"garantiza resultados futuros.")

    tpl = open(TEMPLATE, encoding="utf-8").read()
    html = (tpl.replace("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
            .replace("__UPDATED__", f"{hoy.day} {MESES[hoy.month - 1]} {hoy.year}")
            .replace("__DESC_BEST__", desc_best)
            .replace("__DESC_WORST__", desc_worst)
            .replace("__NOTE__", note))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print("wrote", out_path, len(html), "bytes")
    print(f"mejor {best['p']} {pct(best['pp'])}pp | peor {worst['p']} {pct(worst['pp'])}pp | "
          f"peor dd {worst_dd_w['dd']}% ({worst_dd_w['p']}) | marcador {data['wins']}/{len(windows)}")
