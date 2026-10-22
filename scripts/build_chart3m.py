"""Builds the rolling 3-month gains page (Ganancia últimos 3 meses).

Panel 1 (model vs indexes) re-windows the series already built for the
12-month chart — vintage-pinned data, no extra simulation — so this script
runs AFTER build_chart12m.py in the daily cycle and reads its output HTML.
Panel 2 (live paper book vs S&P) is recomputed fresh from
portfolio_state.json entry prices, same approach as the dashboard tile.

Usage: build_chart3m.py OUT_HTML [CHART12M_HTML]
"""

import json
import re
import sys
from datetime import date

import pandas as pd

from app.data.providers import get_ohlcv

TEMPLATE = "scripts/templates/chart3m_template.html"
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def fmt_date(iso: str) -> str:
    d = date.fromisoformat(iso[:10])
    return f"{d.day} {MESES[d.month - 1]} {d.year}"


def pct(v: float) -> str:
    return f"{'+' if v >= 0 else '−'}{abs(v):.2f}%"


def window_rebase(pts: list[dict], start: str, end: str) -> list[dict]:
    w = [p for p in pts if start <= p["d"] <= end]
    base = w[0]["e"]
    return [{"d": p["d"], "v": round(p["e"] / base * 10000, 2)} for p in w]


if __name__ == "__main__":
    out_path = sys.argv[1] if len(sys.argv) > 1 else "chart_3m.html"
    src12m = sys.argv[2] if len(sys.argv) > 2 else "chart_12m.html"

    html12 = open(src12m, encoding="utf-8").read()
    data12 = json.loads(re.search(r"const DATA\s*=\s*(\{.*?\});", html12, re.S).group(1))

    end = data12["daily"][-1]["d"]
    target = (pd.Timestamp(end) - pd.DateOffset(months=3)).strftime("%Y-%m-%d")
    start = next(p["d"] for p in data12["daily"] if p["d"] >= target)

    panel1 = [{"label": "Modelo", "pts": window_rebase(data12["daily"], start, end)}]
    for x in data12["indexes"]:
        panel1.append({"label": x["label"], "pts": window_rebase(x["pts"], start, end)})

    # Libro real desde sus precios de entrada (datos frescos, como el dashboard)
    state = json.load(open("portfolio_state.json"))
    inception = min(p["entry_date"] for p in state["positions"].values())
    closes = {sym: get_ohlcv(sym, period="1y")["Close"] for sym in state["positions"]}
    idx = closes["^GSPC"].index
    idx = idx[idx >= pd.Timestamp(inception)]
    cash = state.get("cash_weight", 0.0)
    book_pts, spx_pts = [], []
    spx_entry = state["positions"]["^GSPC"]["entry_price"]
    for d in idx:
        v = cash
        complete = True
        for sym, p in state["positions"].items():
            s = closes[sym][closes[sym].index <= d]
            if s.empty:
                complete = False
                break
            v += p["weight"] * float(s.iloc[-1]) / p["entry_price"]
        if not complete:
            continue
        book_pts.append({"d": str(d.date()), "v": round(v * 10000, 2)})
        spx = closes["^GSPC"][closes["^GSPC"].index <= d]
        spx_pts.append({"d": str(d.date()), "v": round(float(spx.iloc[-1]) / spx_entry * 10000, 2)})
    panel2 = [{"label": "Libro real", "pts": book_pts}, {"label": "S&P 500", "pts": spx_pts}]

    rets = {s["label"]: (s["pts"][-1]["v"] / 10000 - 1) * 100 for s in panel1}
    book_ret = (book_pts[-1]["v"] / 10000 - 1) * 100
    spx_book_ret = (spx_pts[-1]["v"] / 10000 - 1) * 100

    # desglose mensual del modelo dentro de la ventana
    months, cur, start_val, last_val = [], None, None, None
    for p in panel1[0]["pts"]:
        mo = p["d"][:7]
        if mo != cur:
            if cur is not None:
                months.append((f"{MESES[int(cur[5:7]) - 1]}", (last_val / start_val - 1) * 100))
            cur, start_val = mo, last_val if last_val is not None else p["v"]
        last_val = p["v"]
    months.append((f"{MESES[int(cur[5:7]) - 1]}", (last_val / start_val - 1) * 100))
    desc1 = (f"Valor de $10,000 invertidos el {fmt_date(start)}. Por mes el modelo hizo: "
             + ", ".join(f"{m} {pct(r)}" for m, r in months) + " (el último mes es parcial).")

    pos_rets = {}
    for sym, p in state["positions"].items():
        s = closes[sym]
        pos_rets[sym] = (float(s.iloc[-1]) / p["entry_price"] - 1) * 100
    best = max(pos_rets, key=pos_rets.get)
    worst = min(pos_rets, key=pos_rets.get)
    wbest = state["positions"][best]["weight"]
    wworst = state["positions"][worst]["weight"]
    desc2 = (f"El libro en papel arrancó el {fmt_date(inception)} con $10,000 a precios de entrada, "
             f"por eso el primer cierre puede aparecer bajo la base. Hoy va en {pct(book_ret)} contra "
             f"{pct(spx_book_ret)} del S&amp;P desde la misma fecha; {best} ({pct(pos_rets[best])}, "
             f"{wbest:.0%} del libro) es el motor y {worst} ({pct(pos_rets[worst])}, {wworst:.0%}) el lastre.")

    note = (f"tres meses es una ventana corta y el modelo es una simulación histórica — el libro real, "
            f"que sí sigue reglas en vivo, va en {pct(book_ret)} desde el {fmt_date(inception)}. "
            f"En la ventana el modelo hizo {pct(rets['Modelo'])} contra {pct(rets['S&P 500'])} del S&amp;P. "
            f"No es asesoría financiera ni garantiza resultados futuros.")

    # Los tiles y las etiquetas se renderizan en el navegador (selector de
    # unidad: del periodo / mensual / anualizada) a partir de __DATA__.
    data = {"panel1": panel1, "panel2": panel2, "window": [start, end]}
    tpl = open(TEMPLATE, encoding="utf-8").read()
    html = (tpl.replace("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":")))
            .replace("__WINDOW__", f"{fmt_date(start)} → {fmt_date(end)}")
            .replace("__DESC1__", desc1)
            .replace("__DESC2__", desc2)
            .replace("__NOTE__", note))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print("wrote", out_path, len(html), "bytes")
    print(f"ventana {start} -> {end} | " + " | ".join(f"{k} {pct(v)}" for k, v in rets.items()))
    print(f"libro {pct(book_ret)} vs S&P {pct(spx_book_ret)} desde {inception}")
