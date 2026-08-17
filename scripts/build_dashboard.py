"""Daily position-monitoring dashboard for the validated default model.

Maintains a committed paper book (portfolio_state.json) and, each run:

1. If no book exists (or a quarterly boundary passed), runs the model's
   selection (regime read -> tilt -> risk-adjusted selection -> risk-parity
   weights) and emits the BUY/rotation orders that build the new book.
2. Otherwise, evaluates each held position against the model's daily rules —
   ensemble signal (SELL >=55% exits to cash), 15% stop-loss from entry —
   and emits concrete orders. Freed capital stays in cash until the next
   quarterly boundary (mid-quarter redeployment was validated and rejected).
3. Writes dashboard.html (artifact page content) to the path given as argv,
   and updates portfolio_state.json.

The book is paper: reference prices are daily closes, sizes are fractions of
a nominal $10,000. It exists so the dashboard's "movements to execute" are
real, stateful diffs — not a stateless scan.
"""

import json
import sys
from pathlib import Path

import pandas as pd

from app.config import EXAMPLE_SYMBOLS
from app.data.providers import get_ohlcv
from app.portfolio import (
    DEFAULT_STOP_LOSS_PCT,
    _apply_equity_tilt,
    _equity_risk_on,
    _risk_parity_weights,
    _select_portfolio,
    _vol_regime_exposure,
)
from app.config import AssetClass, infer_asset_class
from app.data.edgar_client import trailing_eps_known_at
from app.fundamentals.valuation import CHEAP_PE_MAX, EXPENSIVE_PE_MIN, valuation_report
from app.fundamentals.valuation_history import _split_adjusted_quarters
from app.fundamentals.sector_pe import sector_relative_valuation
from app.recommend.engine import recommend

STATE_PATH = Path("portfolio_state.json")
NOMINAL_CAPITAL = 10_000.0
REBALANCE_MONTHS = 3

MONTHS_ES = {1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun", 7: "jul", 8: "ago", 9: "sep", 10: "oct", 11: "nov", 12: "dic"}


def pe_history_series(symbol: str, df: pd.DataFrame, bars: int = 750) -> list[tuple[str, float]]:
    """Point-in-time trailing P/E for the last `bars` sessions: each day's
    close divided by the TTM EPS whose SEC filings were public that day
    (split-adjusted into today's units). Empty on any data failure."""
    try:
        quarters = _split_adjusted_quarters(symbol)
    except Exception:
        return []
    out = []
    for d, close in df["Close"].tail(bars).items():
        eps = trailing_eps_known_at(quarters, str(d.date()))
        if eps and eps > 0:
            out.append((str(d.date()), float(close) / eps))
    return out


def pe_svg(series: list[tuple[str, float]], reference_pe: float | None = None, width: int = 420, height: int = 130) -> str:
    """Small-multiple SVG of the point-in-time P/E path with the fixed
    cheap/expensive bands shaded — the same bands the tilt uses, so the
    picture and the rule are one thing."""
    if len(series) < 20:
        return "<p class='sub'>Sin historial de P/E suficiente para graficar.</p>"
    values = [v for _, v in series]
    lo = min(10.0, min(values), *([reference_pe] if reference_pe else [])) * 0.95
    hi = max(EXPENSIVE_PE_MIN + 5, max(values), *([reference_pe] if reference_pe else [])) * 1.05
    ml, mr, mt, mb = 34, 46, 8, 18

    def x(i):
        return ml + i / (len(series) - 1) * (width - ml - mr)

    def y(v):
        return mt + (1 - (v - lo) / (hi - lo)) * (height - mt - mb)

    pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, (_, v) in enumerate(series))

    def band(v0, v1, cls):
        top, bottom = y(min(v1, hi)), y(max(v0, lo))
        if bottom <= top:
            return ""
        return f"<rect x='{ml}' y='{top:.1f}' width='{width-ml-mr}' height='{bottom-top:.1f}' class='{cls}'/>"

    cheap = band(lo, CHEAP_PE_MAX, "zone-cheap") if lo < CHEAP_PE_MAX else ""
    rich = band(EXPENSIVE_PE_MIN, hi, "zone-rich") if hi > EXPENSIVE_PE_MIN else ""
    gridlines = "".join(
        f"<line x1='{ml}' x2='{width-mr}' y1='{y(v):.1f}' y2='{y(v):.1f}' class='pe-grid'/>"
        f"<text x='{ml-5}' y='{y(v)+3.5:.1f}' text-anchor='end' class='pe-label'>{v:.0f}</text>"
        for v in (CHEAP_PE_MAX, EXPENSIVE_PE_MIN)
        if lo <= v <= hi
    )
    ref_line = ""
    if reference_pe and lo <= reference_pe <= hi:
        ref_line = (
            f"<line x1='{ml}' x2='{width-mr}' y1='{y(reference_pe):.1f}' y2='{y(reference_pe):.1f}' class='pe-ref'/>"
            f"<text x='{width-mr}' y='{y(reference_pe)-4:.1f}' text-anchor='end' class='pe-label'>mediana industria {reference_pe:.0f}</text>"
        )
    return (
        f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='P/E histórico punto-en-tiempo'>"
        f"{cheap}{rich}{gridlines}{ref_line}"
        f"<polyline points='{pts}' class='pe-line'/>"
        f"<circle cx='{x(len(series)-1):.1f}' cy='{y(values[-1]):.1f}' r='3.4' class='pe-dot'/>"
        f"<text x='{x(len(series)-1)+6:.1f}' y='{y(values[-1])+3.5:.1f}' class='pe-label strong'>{values[-1]:.1f}</text>"
        f"<text x='{ml}' y='{height-4}' class='pe-label'>{series[0][0][:7]}</text>"
        f"<text x='{width-mr}' y='{height-4}' text-anchor='end' class='pe-label'>{series[-1][0][:7]}</text>"
        f"</svg>"
    )


def fmt_date(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{int(d)} {MONTHS_ES[int(m)]} {y}"


def fetch_universe() -> dict[str, pd.DataFrame]:
    dfs = {}
    for entry in (e for syms in EXAMPLE_SYMBOLS.values() for e in syms):
        try:
            dfs[entry["symbol"]] = get_ohlcv(entry["symbol"], period="3y")
        except Exception:
            pass
    return dfs


def select_book(dfs: dict[str, pd.DataFrame], as_of: str) -> tuple[dict, bool | None]:
    idx = {s: len(df) for s, df in dfs.items()}
    risk_on = _equity_risk_on(dfs, idx)
    universe, cap = _apply_equity_tilt(dfs, risk_on, 2)
    portfolio = _select_portfolio(universe, idx, 5, False, NOMINAL_CAPITAL, None, 55.0, max_per_asset_class=cap)
    weights = _risk_parity_weights(portfolio) if portfolio else {}
    positions = {}
    for c in portfolio:
        s = c["symbol"]
        price = float(dfs[s]["Close"].iloc[-1])
        positions[s] = {
            "weight": round(weights[s], 4),
            "entry_price": round(price, 4),
            "entry_date": as_of,
            "confidence_at_selection": c["confidence_pct_at_selection"],
        }
    return positions, risk_on


def next_boundary(from_date: str) -> str:
    return str((pd.Timestamp(from_date) + pd.DateOffset(months=REBALANCE_MONTHS)).date())


def main() -> None:
    out_html = sys.argv[1] if len(sys.argv) > 1 else "dashboard.html"
    dfs = fetch_universe()
    if not dfs:
        raise SystemExit("Sin datos de mercado — no se genera dashboard.")
    as_of = str(max(df.index[-1] for df in dfs.values()).date())

    state = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else None
    actions = []

    if state is None:
        positions, risk_on = select_book(dfs, as_of)
        cash_weight = max(0.0, round(1 - sum(p["weight"] for p in positions.values()), 4))
        state = {
            "created": as_of,
            "as_of": as_of,
            "positions": positions,
            "cash_weight": cash_weight,
            "next_rebalance": next_boundary(as_of),
            "regime_risk_on": risk_on,
        }
        for s, p in positions.items():
            actions.append({
                "tipo": "COMPRAR",
                "symbol": s,
                "detalle": f"{p['weight']*100:.1f}% del capital (${p['weight']*NOMINAL_CAPITAL:,.0f} por cada $10,000) a precio de referencia {p['entry_price']:,}",
                "motivo": f"Libro inicial — confianza {p['confidence_at_selection']}% en la selección",
            })
    elif as_of >= state["next_rebalance"]:
        old = set(state["positions"])
        positions, risk_on = select_book(dfs, as_of)
        for s in sorted(old - set(positions)):
            actions.append({"tipo": "VENDER", "symbol": s, "detalle": "salir por rotación trimestral", "motivo": "Re-selección trimestral: ya no está entre los elegidos"})
        for s in sorted(set(positions) - old):
            p = positions[s]
            actions.append({"tipo": "COMPRAR", "symbol": s, "detalle": f"{p['weight']*100:.1f}% del capital", "motivo": f"Re-selección trimestral — confianza {p['confidence_at_selection']}%"})
        for s in sorted(old & set(positions)):
            old_w, new_w = state["positions"][s]["weight"], positions[s]["weight"]
            if abs(new_w - old_w) > 0.02:
                actions.append({"tipo": "AJUSTAR", "symbol": s, "detalle": f"peso {old_w*100:.1f}% -> {new_w*100:.1f}%", "motivo": "Re-ponderación por risk parity"})
        state.update({
            "as_of": as_of,
            "positions": positions,
            "cash_weight": max(0.0, round(1 - sum(p["weight"] for p in positions.values()), 4)),
            "next_rebalance": next_boundary(as_of),
            "regime_risk_on": risk_on,
        })
    else:
        idx = {s: len(df) for s, df in dfs.items()}
        state["regime_risk_on"] = _equity_risk_on(dfs, idx)
        for s in list(state["positions"]):
            if s not in dfs:
                continue
            p = state["positions"][s]
            price = float(dfs[s]["Close"].iloc[-1])
            loss_pct = (price / p["entry_price"] - 1) * 100
            rec = recommend(dfs[s], symbol=s, initial_capital=NOMINAL_CAPITAL, commission_bps=None, allow_short=False)
            if loss_pct <= -DEFAULT_STOP_LOSS_PCT:
                actions.append({"tipo": "VENDER", "symbol": s, "detalle": f"salir a efectivo ({loss_pct:+.1f}% desde la entrada)", "motivo": f"Stop-loss del {DEFAULT_STOP_LOSS_PCT:.0f}% disparado"})
                del state["positions"][s]
            elif rec["overall_action"] == "SELL" and rec["confidence_pct"] >= 55.0:
                actions.append({"tipo": "VENDER", "symbol": s, "detalle": "salir a efectivo", "motivo": f"Señal SELL con {rec['confidence_pct']}% de confianza"})
                del state["positions"][s]
        state["cash_weight"] = max(0.0, round(1 - sum(p["weight"] for p in state["positions"].values()), 4))
        state["as_of"] = as_of

    # --- per-position monitoring rows ---
    rows = []
    for s, p in state["positions"].items():
        df = dfs.get(s)
        if df is None:
            continue
        price = float(df["Close"].iloc[-1])
        pnl = (price / p["entry_price"] - 1) * 100
        pnl = pnl if abs(pnl) > 0.005 else 0.0
        rec = recommend(df, symbol=s, initial_capital=NOMINAL_CAPITAL, commission_bps=None, allow_short=False)
        exposure = float(_vol_regime_exposure(df["Close"]).iloc[-1]) * 100
        stop_level = p["entry_price"] * (1 - DEFAULT_STOP_LOSS_PCT / 100)
        pe = None
        if infer_asset_class(s) is AssetClass.STOCK:
            try:
                pe = valuation_report(s).get("trailing_pe")
            except Exception:
                pe = None
        rows.append({
            "symbol": s, "weight": p["weight"], "entry_price": p["entry_price"], "entry_date": p["entry_date"],
            "price": price, "pnl_pct": pnl, "signal": rec["overall_action"], "signal_conf": rec["confidence_pct"],
            "exposure_pct": exposure, "stop_level": stop_level, "pe": pe,
            "stop_distance_pct": (price / stop_level - 1) * 100,
        })
    rows.sort(key=lambda r: -r["weight"])

    # --- fundamental valuation cards for stock positions ---
    valuation_cards = []
    for r in rows:
        s = r["symbol"]
        if infer_asset_class(s) is not AssetClass.STOCK or s not in dfs:
            continue
        try:
            vrep = valuation_report(s)
        except Exception:
            vrep = {}
        guidance_txt = {"bullish": "revisiones al alza", "bearish": "revisiones a la baja", "neutral": "revisiones estables"}.get(
            vrep.get("guidance_signal", "neutral"), "sin lectura"
        )
        rel = sector_relative_valuation(s, vrep.get("trailing_pe"))
        valuation_cards.append({
            "symbol": s,
            "trailing_pe": vrep.get("trailing_pe"),
            "implicit_forward_pe": vrep.get("implicit_forward_pe"),
            "guidance_txt": guidance_txt,
            "guidance_signal": vrep.get("guidance_signal", "neutral"),
            "industry": rel.get("industry") or rel.get("sector") or "",
            "relative_reading": rel.get("reading", "sin referencia"),
            "relative_ratio": rel.get("ratio"),
            "reference_pe": rel.get("reference_pe"),
            "svg": pe_svg(pe_history_series(s, dfs[s]), rel.get("reference_pe")),
        })

    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")

    # --- render ---
    regime_txt = "ALCISTA — 100% acciones e índices" if state["regime_risk_on"] else ("DEFENSIVO — universo completo" if state["regime_risk_on"] is False else "sin lectura")
    def money(w):
        return f"${w*NOMINAL_CAPITAL:,.0f}"

    def valcard_html(c: dict) -> str:
        tr = f"{c['trailing_pe']:.1f}" if c.get("trailing_pe") else "—"
        fw = f"{c['implicit_forward_pe']:.1f}" if c.get("implicit_forward_pe") else "—"
        warn = " warn" if c["guidance_signal"] == "bearish" else ""
        ratio_txt = f" ({c['relative_ratio']:.2f}x)" if c.get("relative_ratio") else ""
        rel_cls = " good" if "barata" in c["relative_reading"] else (" warn" if "cara" in c["relative_reading"] else "")
        return (
            f"<div class='valcard'><h3>{c['symbol']} <span class='sub'>{c['industry']}</span></h3>"
            f"<div class='chips'><span class='chip2'>P/E actual {tr}</span>"
            f"<span class='chip2'>fwd implícito {fw}</span>"
            f"<span class='chip2{warn}'>guidance: {c['guidance_txt']}</span>"
            f"<span class='chip2{rel_cls}'>vs industria: {c['relative_reading']}{ratio_txt}</span></div>"
            f"{c['svg']}</div>"
        )

    valuation_html = (
        "<div class='valgrid'>" + "".join(valcard_html(c) for c in valuation_cards) + "</div>"
        if valuation_cards
        else "<p class='allclear'>El libro actual no tiene acciones individuales — los índices no tienen P/E por símbolo.</p>"
    )

    action_html = "".join(
        f"<div class='action {a['tipo'].lower()}'><span class='badge'>{a['tipo']}</span>"
        f"<div><strong>{a['symbol']}</strong> — {a['detalle']}<div class='why'>{a['motivo']}</div></div></div>"
        for a in actions
    ) or "<p class='allclear'>Sin movimientos hoy: todas las posiciones conservan su señal, ningún stop-loss disparado y la próxima re-selección no ha llegado.</p>"

    def row_html(r: dict) -> str:
        pe_txt = f"{r['pe']:.1f}" if r["pe"] else "—"
        return (
            f"<tr><td><strong>{r['symbol']}</strong><div class='sub'>desde {fmt_date(r['entry_date'])}</div></td>"
            f"<td class='num'>{r['weight']*100:.1f}%<div class='sub'>{money(r['weight'])}</div></td>"
            f"<td class='num'>{r['entry_price']:,.2f}</td><td class='num'>{r['price']:,.2f}</td>"
            f"<td class='num {'up' if r['pnl_pct'] >= 0 else 'down'}'>{r['pnl_pct']:+.2f}%</td>"
            f"<td>{r['signal']} <span class='sub'>{r['signal_conf']:.0f}%</span></td>"
            f"<td class='num'>{r['exposure_pct']:.0f}%</td>"
            f"<td class='num'>{pe_txt}</td>"
            f"<td class='num'>{r['stop_level']:,.2f}<div class='sub'>a {r['stop_distance_pct']:.1f}%</div></td></tr>"
        )

    pos_html = "".join(row_html(r) for r in rows)

    html = f"""<title>Monitor del portafolio</title>
<style>
  :root {{ color-scheme: light; --surface:#fcfcfb; --card:#f4f3f0; --ink:#0b0b0b; --ink2:#52514e; --ink3:#8a8880;
    --grid:#e6e4df; --pos:#2a78d6; --neg:#e34948; --soft:rgba(42,120,214,.14); --softneg:rgba(227,73,72,.12); }}
  @media (prefers-color-scheme: dark) {{ :root:where(:not([data-theme="light"])) {{ color-scheme: dark;
    --surface:#1a1a19; --card:#232322; --ink:#fff; --ink2:#c3c2b7; --ink3:#8a8880; --grid:#33332f;
    --pos:#3987e5; --neg:#e66767; --soft:rgba(57,135,229,.22); --softneg:rgba(230,103,103,.18); }} }}
  :root[data-theme="dark"] {{ color-scheme: dark; --surface:#1a1a19; --card:#232322; --ink:#fff; --ink2:#c3c2b7;
    --ink3:#8a8880; --grid:#33332f; --pos:#3987e5; --neg:#e66767; --soft:rgba(57,135,229,.22); --softneg:rgba(230,103,103,.18); }}
  :root[data-theme="light"] {{ color-scheme: light; --surface:#fcfcfb; --card:#f4f3f0; --ink:#0b0b0b; --ink2:#52514e;
    --ink3:#8a8880; --grid:#e6e4df; --pos:#2a78d6; --neg:#e34948; --soft:rgba(42,120,214,.14); --softneg:rgba(227,73,72,.12); }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:var(--surface); color:var(--ink); font:15px/1.55 "Avenir Next","Segoe UI",system-ui,sans-serif; }}
  main {{ max-width: 960px; margin:0 auto; padding:36px 24px 64px; }}
  .eyebrow {{ font-size:12px; letter-spacing:.14em; text-transform:uppercase; color:var(--ink3); margin:0 0 6px; }}
  h1 {{ font-size:clamp(22px,4vw,30px); margin:0 0 20px; }}
  .tiles {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:12px; margin-bottom:30px; }}
  .tile {{ background:var(--card); border-radius:10px; padding:12px 16px; }}
  .tile .k {{ font-size:11px; letter-spacing:.1em; text-transform:uppercase; color:var(--ink3); }}
  .tile .v {{ font-size:19px; font-weight:700; margin-top:2px; }}
  h2 {{ font-size:17px; margin:28px 0 10px; }}
  .action {{ display:flex; gap:12px; align-items:flex-start; background:var(--card); border-radius:10px; padding:12px 14px; margin-bottom:8px; }}
  .badge {{ font-size:11px; font-weight:700; letter-spacing:.06em; padding:2px 9px; border-radius:6px; background:var(--soft); color:var(--pos); white-space:nowrap; margin-top:2px; }}
  .action.vender .badge {{ background:var(--softneg); color:var(--neg); }}
  .why {{ font-size:12.5px; color:var(--ink2); }}
  .allclear {{ background:var(--card); border-radius:10px; padding:14px 16px; color:var(--ink2); }}
  table {{ border-collapse:collapse; width:100%; font-size:13.5px; }}
  th,td {{ text-align:left; padding:9px 10px; border-bottom:1px solid var(--grid); vertical-align:top; }}
  th {{ font-size:11px; letter-spacing:.08em; text-transform:uppercase; color:var(--ink3); }}
  td.num,th.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .up {{ color:var(--pos); }} .down {{ color:var(--neg); }}
  .sub {{ font-size:11.5px; color:var(--ink3); }}
  .note {{ background:var(--card); border-radius:10px; padding:13px 16px; color:var(--ink2); font-size:13px; margin-top:28px; }}
  .valgrid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:14px; }}
  .valcard {{ background:var(--card); border-radius:10px; padding:14px 16px; }}
  .valcard h3 {{ margin:0 0 8px; font-size:15px; }}
  .chips {{ display:flex; flex-wrap:wrap; gap:6px; margin-bottom:10px; }}
  .chip2 {{ font-size:12px; padding:2px 9px; border-radius:6px; background:var(--soft); }}
  .chip2.warn {{ background:var(--softneg); }}
  .chip2.good {{ background:var(--soft); font-weight:600; }}
  .pe-ref {{ stroke:var(--ink2); stroke-width:1.4; stroke-dasharray:6 4; }}
  .pe-line {{ fill:none; stroke:var(--pos); stroke-width:2; stroke-linejoin:round; }}
  .pe-dot {{ fill:var(--pos); }}
  .pe-grid {{ stroke:var(--ink3); stroke-width:1; stroke-dasharray:3 4; opacity:.6; }}
  .pe-label {{ fill:var(--ink3); font-size:10.5px; font-variant-numeric:tabular-nums; }}
  .pe-label.strong {{ fill:var(--ink); font-weight:600; font-size:11.5px; }}
  .zone-cheap {{ fill:var(--soft); opacity:.55; }}
  .zone-rich {{ fill:var(--softneg); opacity:.55; }}
  svg {{ display:block; width:100%; height:auto; }}
  .tablewrap {{ overflow-x:auto; }}
</style>
<main>
  <p class="eyebrow">Monitor diario · datos al {fmt_date(as_of)} · libro nominal de $10,000</p>
  <h1>Portafolio del modelo</h1>
  <div class="tiles">
    <div class="tile"><div class="k">Régimen</div><div class="v">{regime_txt.split(' — ')[0]}</div><div class="sub">{regime_txt.split(' — ')[1] if ' — ' in regime_txt else ''}</div></div>
    <div class="tile"><div class="k">Posiciones</div><div class="v">{len(rows)}</div><div class="sub">efectivo: {state['cash_weight']*100:.1f}% ({money(state['cash_weight'])})</div></div>
    <div class="tile"><div class="k">Próxima re-selección</div><div class="v">{fmt_date(state['next_rebalance'])}</div><div class="sub">o antes si una señal saca una posición</div></div>
  </div>

  <h2>Movimientos a ejecutar hoy</h2>
  {action_html}

  <h2>Posiciones bajo monitoreo</h2>
  <div class="tablewrap"><table>
    <thead><tr><th>Símbolo</th><th class="num">Peso</th><th class="num">Entrada</th><th class="num">Actual</th>
    <th class="num">P&amp;L</th><th>Señal hoy</th><th class="num">Exposición vol.</th><th class="num">P/E</th><th class="num">Stop-loss</th></tr></thead>
    <tbody>{pos_html}</tbody>
  </table></div>

  <h2>Valuación fundamental (acciones del libro)</h2>
  <p class="sub" style="font-size:13px;margin:0 0 12px;">La línea es el P/E <em>punto-en-tiempo</em>
  (precio del día entre las utilidades que eran públicas ese día, SEC EDGAR, últimos 3 años). Zona azul: barata
  (&lt;{CHEAP_PE_MAX:.0f}); zona roja: cara (&gt;{EXPENSIVE_PE_MIN:.0f}) — las mismas bandas fijas que usa la señal.
  "Guidance" es la dirección de las revisiones de estimados de analistas en 90 días; "fwd implícito" = precio entre
  el EPS consenso del próximo año. La línea punteada es la <em>mediana de referencia de su industria</em>
  (tabla fija tipo Damodaran) y el chip "vs industria" lee el cociente: &lt;0.8x barata para su industria,
  &gt;1.2x cara — porque un P/E de 27 es normal en software y carísimo en automotrices.</p>
  {valuation_html}

  <p class="note"><strong>Cómo leerlo:</strong> "Señal hoy" es la lectura diaria del ensemble — un SELL ≥55% genera
  la orden de salida a efectivo al día siguiente. "Exposición vol." es el ajuste del régimen de volatilidad (100% =
  tamaño completo). "P/E" es el múltiplo precio/utilidades actual (solo acciones; informativo — bandas clásicas:
  &lt;15 barata, &gt;30 cara). El stop-loss marca el precio que fuerza la salida (−15% desde la entrada) y a qué distancia está.
  El efectivo liberado espera hasta la re-selección trimestral — el redespliegue inmediato se probó y se rechazó.
  Libro de papel con precios de cierre; no es asesoría financiera ni garantiza resultados futuros.</p>
</main>
"""
    Path(out_html).write_text(html)
    print(json.dumps({"as_of": as_of, "actions": actions, "positions": len(rows), "cash_weight": state["cash_weight"], "next_rebalance": state["next_rebalance"]}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
