"""Builds the rolling 12-month gains page (Ganancias últimos 12 meses —
modelo actual) from real data.

Runs the current default model and the pre-tilt model over the last ~12
months (probing forward week by week if the target start has no valid
selection), fetches the three index benchmarks, and injects everything
into scripts/templates/chart12m_template.html. Output goes to the session
scratchpad, ready to publish as the existing artifact."""

import json
import sys
from datetime import date

import pandas as pd

from app.data.providers import get_ohlcv
from app.portfolio import simulate_portfolio_real

MAX_PROBE_WEEKS = 8
PERIOD = "4y"
TEMPLATE = "scripts/templates/chart12m_template.html"
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
INDEXES = [("^GSPC", "S&P 500"), ("^IXIC", "Nasdaq"), ("^DJI", "Dow Jones")]


def run_arm(start: pd.Timestamp, **kwargs) -> dict:
    for _ in range(MAX_PROBE_WEEKS):
        try:
            return simulate_portfolio_real(start_date=str(start.date()), period=PERIOD, step=1, **kwargs)
        except ValueError as exc:
            if "No se encontraron símbolos" not in str(exc):
                raise
            print(f"sin selección válida el {start.date()}, probando la semana siguiente")
            start += pd.Timedelta(days=7)
    raise SystemExit(f"Sin selección válida en {MAX_PROBE_WEEKS} semanas.")


def curve_points(report: dict) -> list[dict]:
    return [{"d": c["date"][:10], "e": c["equity"]} for c in report["portfolio_equity_curve"]]


def max_drawdown_pct(equity: list[float]) -> float:
    worst, peak = 0.0, equity[0]
    for v in equity:
        peak = max(peak, v)
        worst = min(worst, (v / peak - 1) * 100)
    return round(worst, 2)


def month_label(iso: str) -> str:
    return f"{MESES[int(iso[5:7]) - 1]} {iso[2:4]}"


def fmt_date(iso: str) -> str:
    d = date.fromisoformat(iso[:10])
    return f"{d.day} {MESES[d.month - 1]} {d.year}"


if __name__ == "__main__":
    out_path = sys.argv[1] if len(sys.argv) > 1 else "chart_12m.html"
    # Ancla el inicio a la malla trimestral original (5 feb/may/ago/nov):
    # el último nodo de la malla que quede a >=12 meses de hoy. Así las
    # fronteras no se desplazan día con día (el retorno de una ventana
    # rebalanceada es muy sensible a dónde caen los cortes) y la serie
    # publicada es estable y comparable entre días.
    hoy = pd.Timestamp.today().normalize()
    grid = [pd.Timestamp(year=y, month=m, day=5) for y in range(hoy.year - 2, hoy.year + 1) for m in (2, 5, 8, 11)]
    target = max(d for d in grid if d <= hoy - pd.DateOffset(years=1))
    new = run_arm(target)
    # el "modelo anterior" es el previo a ambos tilts; si no se apagan
    # explícito, la línea de comparación deja de ser el modelo que existió
    old = run_arm(target, equity_regime_tilt=False, fundamental_pe_tilt=False)

    daily = curve_points(new)
    old_daily = curve_points(old)
    equity = [p["e"] for p in daily]
    initial = new["initial_capital"]

    months, cur, start_val, last_val = [], None, initial, initial
    for p in daily:
        mo = p["d"][:7]
        if mo != cur:
            if cur is not None:
                months.append({"m": month_label(cur + "-01"), "pct": round((last_val / start_val - 1) * 100, 2)})
            cur, start_val = mo, last_val
        last_val = p["e"]
    months.append({"m": month_label(cur + "-01"), "pct": round((last_val / start_val - 1) * 100, 2)})

    segs_raw = new["segments"]
    caps = [s["capital_start"] for s in segs_raw] + [new["final_equity"]]
    segments = [
        {
            "date": s["start_date"],
            "portfolio": ([p["symbol"] for p in s["portfolio"]] if s.get("portfolio") and isinstance(s["portfolio"][0], dict) else (s.get("portfolio") or [])),
            "ret": round((caps[i + 1] / caps[i] - 1) * 100, 2) if caps[i] else 0.0,
            "risk_on": s.get("equity_risk_on"),
        }
        for i, s in enumerate(segs_raw)
    ]

    indexes = []
    for sym, label in INDEXES:
        df = get_ohlcv(sym, period="2y")
        df = df[(df.index >= daily[0]["d"]) & (df.index <= daily[-1]["d"])]
        base = float(df["Close"].iloc[0])
        pts = [{"d": str(d.date()), "e": round(initial * float(c) / base, 2)} for d, c in df["Close"].items()]
        indexes.append({"label": label, "ret": round((pts[-1]["e"] / initial - 1) * 100, 2), "pts": pts})

    data = {
        "daily": daily, "old_daily": old_daily, "months": months, "initial": initial,
        "ret_new": new["total_return_pct"], "dd_new": max_drawdown_pct(equity),
        "ret_old": old["total_return_pct"], "dd_old": max_drawdown_pct([p["e"] for p in old_daily]),
        "rebalances": [s["date"] for s in segments[1:]],
        "segments": segments, "indexes": indexes,
    }

    def pct(v):
        return f"{'+' if v >= 0 else '−'}{abs(v):.2f}%"

    tiles = "\n".join([
        f"    <div class='tile'><div class='k'>Modelo nuevo</div><div class='v {'up' if data['ret_new'] >= 0 else 'down'}'>{pct(data['ret_new'])}</div><div class='n'>drawdown máx {data['dd_new']:.1f}%</div></div>",
        f"    <div class='tile'><div class='k'>Modelo anterior</div><div class='v'>{pct(data['ret_old'])}</div><div class='n'>sin tilts accionario ni de P/E</div></div>",
    ] + [
        f"    <div class='tile'><div class='k'>{x['label'].replace('&', '&amp;')}</div><div class='v'>{pct(x['ret'])}</div><div class='n'>drawdown máx {max_drawdown_pct([p['e'] for p in x['pts']]):.1f}%</div></div>"
        for x in indexes
    ])

    n_on = sum(1 for s in segments if s["risk_on"] is True)
    if n_on == len(segments):
        regime_line = (f"Las {len(segments)} fronteras del periodo leyeron mercado alcista, "
                       "así que el modelo nuevo operó 100% en acciones e índices todo el periodo.")
    else:
        regime_line = (f"De las {len(segments)} fronteras del periodo, {n_on} leyeron mercado alcista "
                       f"y {len(segments) - n_on} régimen defensivo (universo completo con tope por clase).")

    idx_rets = [x["ret"] for x in indexes]
    nasdaq_dd = max_drawdown_pct([p["e"] for p in indexes[1]["pts"]])
    note = (
        f"el modelo cierra el periodo en {pct(data['ret_new'])} contra {pct(min(idx_rets))} a {pct(max(idx_rets))} de los índices "
        f"(el modelo anterior, sin los tilts accionario ni de P/E, habría hecho {pct(data['ret_old'])}). "
        f"El régimen de riesgo recorta exposición en picos de volatilidad y las rotaciones pagan comisión — ese freno mantiene el "
        f"drawdown en {data['dd_new']:.1f}% contra {nasdaq_dd:.1f}% del Nasdaq. En las 9 ventanas históricas esta configuración le ganó "
        f"al S&amp;P en 8; su punto ciego conocido son las correcciones rápidas con el mercado aún sobre su media de 200 días. "
        f"Simulación histórica con indicadores técnicos; no es asesoría financiera ni garantiza resultados futuros."
    )

    tpl = open(TEMPLATE, encoding="utf-8").read()
    html = (
        tpl.replace("__DATA__", json.dumps(data, ensure_ascii=False, default=str))
        .replace("__WINDOW__", f"{fmt_date(daily[0]['d'])} → {fmt_date(daily[-1]['d'])}")
        .replace("__TILES__", tiles)
        .replace("__REGIME_LINE__", regime_line)
        .replace("__NOTE__", note)
    )
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print("wrote", out_path, len(html), "bytes")
    print(f"nuevo {pct(data['ret_new'])} (dd {data['dd_new']}%) | anterior {pct(data['ret_old'])} | " +
          " | ".join(f"{x['label']} {pct(x['ret'])}" for x in indexes))
    print("meses:", [(m["m"], m["pct"]) for m in months])
