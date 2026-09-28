"""Builds the 5-strategy comparison page (Comparación de 5 estrategias de
inversión) from real S&P 500 data over the last 3 years.

Runs the single-symbol simulator over ^GSPC for each strategy family,
computes SMA200 regime bands and a buy-and-hold reference, and injects
everything into scripts/templates/compare5_template.html. Output goes to
the session scratchpad, ready to publish as the existing artifact."""

import json
import sys
from datetime import date

import pandas as pd

from app.data.providers import get_ohlcv
from app.simulate import simulate_symbol

SYMBOL = "^GSPC"
PERIOD = "3y"
TEMPLATE = "scripts/templates/compare5_template.html"
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


def sma200_regimes(price_dates: list[str]) -> list[list]:
    """Above/below-SMA200 bands (computed with 5y context) mapped onto the
    simulated window, with micro-segments and same-label neighbors merged."""
    df5 = get_ohlcv(SYMBOL, period="5y")
    above = df5["Close"] > df5["Close"].rolling(200).mean()
    state = above.reindex(pd.to_datetime(price_dates)).fillna(False).tolist()
    segments = []
    cur, start = None, 0
    for i, v in enumerate(state):
        lbl = "sobre SMA200" if v else "bajo SMA200"
        if cur is None:
            cur, start = lbl, i
        elif lbl != cur:
            segments.append([cur, start, i - 1])
            cur, start = lbl, i
    segments.append([cur, start, len(state) - 1])
    merged = []
    for seg in segments:
        if merged and ((seg[2] - seg[1]) < 10 or merged[-1][0] == seg[0]):
            merged[-1][2] = seg[2]
        else:
            merged.append(seg)
    return merged


def fmt_month(iso: str) -> str:
    d = date.fromisoformat(iso[:10])
    return f"{MESES[d.month - 1]} {d.year}"


if __name__ == "__main__":
    out_path = sys.argv[1] if len(sys.argv) > 1 else "compare5.html"
    report = simulate_symbol(SYMBOL, period=PERIOD, allow_short=True)
    dates = [p["date"][:10] for p in report["price_series"]]
    report["regimes"] = sma200_regimes(dates)
    closes = [p["close"] for p in report["price_series"]]
    bh = [round(10000.0 * c / closes[0], 2) for c in closes]

    tpl = open(TEMPLATE, encoding="utf-8").read()
    html = tpl.replace("__DATA__", json.dumps({"report": report, "buy_hold_equity": bh}, ensure_ascii=False, default=str))
    html = html.replace("__WINDOW__", f"{fmt_month(dates[0])} → {fmt_month(dates[-1])}")
    hoy = date.today()
    html = html.replace("__UPDATED__", f"{hoy.day} {MESES[hoy.month - 1]} {hoy.year}")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print("wrote", out_path, len(html), "bytes")
    for r in report["results"]:
        m = r["metrics"]
        print(f"  {r['strategy']:32s} ret={m['total_return_pct']:+7.2f}% g/op={m['avg_profit_per_trade_pct']:+5.2f}% n={m['num_trades']}")
    print("buy_hold final:", bh[-1])
