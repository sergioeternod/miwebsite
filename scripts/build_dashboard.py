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

Page anatomy (mesa-de-operaciones style): summary tiles, today's orders,
expandable ledger rows per position (the drilldown carries the arithmetic
and its sources), a watchlist of out-of-book candidates, an event radar
(what has to happen for the next decision), fundamental valuation cards,
and a data-sources index. Every number that matters has a "fuente y
cálculo" drilldown — plain <details>, no JS.
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
from app.data.yahoo_quote_client import get_calendar_events, get_valuation_metrics
from app.fundamentals.valuation import CHEAP_PE_MAX, EXPENSIVE_PE_MIN, valuation_report
from app.fundamentals.valuation_history import _split_adjusted_quarters, get_split_events
from app.fundamentals.sector_pe import sector_relative_valuation
from app.recommend.engine import recommend

STATE_PATH = Path("portfolio_state.json")
SIGNALS_LOG_PATH = Path("signals_log.jsonl")
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


def pe_svg(series: list[tuple[str, float]], reference_pe: float | None = None, forward_pe: float | None = None, width: int = 420, height: int = 130) -> str:
    """Small-multiple SVG of the point-in-time P/E path with the fixed
    cheap/expensive bands shaded — the same bands the tilt uses, so the
    picture and the rule are one thing. `forward_pe` (el implícito del
    consenso +1y) se dibuja como rombo hueco al final de la serie: hacia
    dónde iría el múltiplo si los estimados se cumplen."""
    if len(series) < 20:
        return "<p class='sub'>Sin historial de P/E suficiente para graficar.</p>"
    values = [v for _, v in series]
    extras = [v for v in (reference_pe, forward_pe) if v]
    lo = min(10.0, min(values), *extras) * 0.95
    hi = max(EXPENSIVE_PE_MIN + 5, max(values), *extras) * 1.05
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
        # Eje: el valor del benchmark, salvo que ya exista un tick 15/30 pegado a él.
        axis_tick = ""
        if not any(abs(reference_pe - v) < 3.5 for v in (CHEAP_PE_MAX, EXPENSIVE_PE_MIN) if lo <= v <= hi):
            axis_tick = (
                f"<text x='{ml-5}' y='{y(reference_pe)+3.5:.1f}' text-anchor='end' class='pe-label ref'>{reference_pe:.0f}</text>"
            )
        ref_line = (
            f"<line x1='{ml}' x2='{width-mr}' y1='{y(reference_pe):.1f}' y2='{y(reference_pe):.1f}' class='pe-ref'/>"
            f"{axis_tick}"
            f"<text x='{ml+6}' y='{y(reference_pe)-5:.1f}' class='pe-label ref halo'>P/E industria {reference_pe:.0f}</text>"
        )
    fwd_marker = ""
    if forward_pe and lo <= forward_pe <= hi:
        fx, fy, ly = x(len(series) - 1), y(forward_pe), y(forward_pe) + 3.5
        # Si el label del forward cae encima del label del último P/E, se desplaza.
        if abs(fy - y(values[-1])) < 13:
            ly = fy + (15 if fy >= y(values[-1]) else -9)
        fwd_marker = (
            f"<path d='M {fx:.1f} {fy-4.4:.1f} L {fx+4.4:.1f} {fy:.1f} L {fx:.1f} {fy+4.4:.1f} L {fx-4.4:.1f} {fy:.1f} Z' class='pe-fwd'/>"
            f"<text x='{fx+7:.1f}' y='{ly:.1f}' class='pe-label fwdlbl'>fwd {forward_pe:.1f}</text>"
        )
    return (
        f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='P/E histórico punto-en-tiempo'>"
        f"{cheap}{rich}{gridlines}{ref_line}"
        f"<polyline points='{pts}' class='pe-line'/>"
        f"{fwd_marker}"
        f"<circle cx='{x(len(series)-1):.1f}' cy='{y(values[-1]):.1f}' r='3.4' class='pe-dot'/>"
        f"<text x='{x(len(series)-1)+6:.1f}' y='{y(values[-1])+3.5:.1f}' class='pe-label strong'>{values[-1]:.1f}</text>"
        f"<text x='{ml}' y='{height-4}' class='pe-label'>{series[0][0][:7]}</text>"
        f"<text x='{width-mr}' y='{height-4}' text-anchor='end' class='pe-label'>{series[-1][0][:7]}</text>"
        f"</svg>"
    )


def guidance_svg(estimates: dict, trailing_eps: float | None = None, width: int = 420, height: int = 100) -> str:
    """Dumbbell del guidance: para cada año fiscal, el EPS consenso hace 90
    días (punto hueco) contra el de hoy (punto sólido), sobre una escala
    común de EPS. La dirección y magnitud del desplazamiento ES la señal de
    guidance; el EPS de los últimos 12 meses ancla la escala como referencia
    de lo ya reportado."""
    rows = []
    for key, label in (("0y", "FY en curso"), ("+1y", "FY siguiente")):
        e = estimates.get(key) or {}
        if e.get("eps_avg") and e.get("eps_avg_90d_ago"):
            rows.append((label, float(e["eps_avg_90d_ago"]), float(e["eps_avg"])))
    if not rows:
        return "<p class='sub'>Sin estimados de analistas para graficar guidance.</p>"
    vals = [v for _, a, b in rows for v in (a, b)]
    if trailing_eps and trailing_eps > 0:
        vals.append(float(trailing_eps))
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.15 or max(abs(hi), 1.0) * 0.05
    lo, hi = lo - pad, hi + pad
    ml, mr, mt, mb = 92, 104, 8, 20

    def x(v):
        return ml + (v - lo) / (hi - lo) * (width - ml - mr)

    row_h = (height - mt - mb) / len(rows)
    parts = []
    if trailing_eps and trailing_eps > 0 and lo <= trailing_eps <= hi:
        parts.append(f"<line x1='{x(trailing_eps):.1f}' x2='{x(trailing_eps):.1f}' y1='{mt}' y2='{height-mb}' class='pe-grid'/>")
        parts.append(f"<text x='{x(trailing_eps):.1f}' y='{height-6}' text-anchor='middle' class='pe-label'>EPS 12m {trailing_eps:.2f}</text>")
    for i, (label, a, b) in enumerate(rows):
        cy = mt + row_h * (i + 0.5)
        chg = (b - a) / abs(a) * 100 if a else 0.0
        cls = " up" if chg > 0.5 else (" down" if chg < -0.5 else "")
        parts.append(f"<text x='{ml-8}' y='{cy+3.5:.1f}' text-anchor='end' class='pe-label'>{label}</text>")
        parts.append(f"<line x1='{x(a):.1f}' x2='{x(b):.1f}' y1='{cy:.1f}' y2='{cy:.1f}' class='g-link{cls}'/>")
        parts.append(f"<circle cx='{x(a):.1f}' cy='{cy:.1f}' r='3' class='g-old'/>")
        parts.append(f"<circle cx='{x(b):.1f}' cy='{cy:.1f}' r='3.6' class='g-new{cls}'/>")
        parts.append(f"<text x='{width-mr+8:.1f}' y='{cy+3.5:.1f}' class='pe-label{cls}'>{b:.2f} ({chg:+.1f}%)</text>")
    return (
        f"<svg viewBox='0 0 {width} {height}' role='img' aria-label='Guidance: estimados EPS hace 90 días contra hoy'>"
        + "".join(parts)
        + "</svg>"
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


def edgar_ttm_detail(symbol: str, as_of: str) -> dict | None:
    """Los 4 trimestres EDGAR que sustentan el P/E actual: fin de periodo,
    fecha de presentación (la compuerta causal) y EPS en unidades de hoy.
    None si no hay 4 trimestres presentados a la fecha."""
    try:
        quarters = _split_adjusted_quarters(symbol)
        splits = get_split_events(symbol)
    except Exception:
        return None
    known = sorted((q for q in quarters if q["filed"] <= as_of), key=lambda q: q["end"], reverse=True)[:4]
    if len(known) < 4:
        return None
    return {"quarters": known, "ttm": sum(q["eps"] for q in known), "num_splits": len(splits)}


# Índices sin P/E propio: el ETF que replica cada uno sí reporta múltiplo.
INDEX_PE_PROXY = {"^GSPC": "SPY", "^DJI": "DIA", "^IXIC": "QQQ"}


def beta_vs_benchmark(df: pd.DataFrame, bench: pd.DataFrame) -> float | None:
    """Beta clásica: cov(retornos diarios, benchmark) / var(benchmark),
    sobre la historia común disponible (~3 años). None con <60 días."""
    joined = pd.concat(
        [df["Close"].pct_change(), bench["Close"].pct_change()], axis=1, join="inner"
    ).dropna()
    if len(joined) < 60:
        return None
    r, m = joined.iloc[:, 0], joined.iloc[:, 1]
    var = float(m.var())
    if var == 0:
        return None
    return float(r.cov(m) / var)


def proxy_pe(symbol: str | None) -> tuple[float | None, str | None]:
    """(P/E, tipo) para un proxy ETF — forward si Yahoo lo reporta, si no
    trailing. (None, None) si no hay proxy o la consulta falla."""
    if not symbol:
        return None, None
    try:
        m = get_valuation_metrics(symbol)
    except Exception:
        return None, None
    if m.get("forward_pe"):
        return float(m["forward_pe"]), "forward"
    if m.get("trailing_pe"):
        return float(m["trailing_pe"]), "trailing"
    return None, None


def sma_cross_state(df: pd.DataFrame, fast: int = 20, slow: int = 50) -> dict | None:
    """Estado del cruce de medias móviles de la estrategia original
    (SmaCrossoverStrategy 20/50): lado actual, distancia entre medias y
    fecha del último cruce. Señal puramente del propio activo."""
    close = df["Close"]
    if len(close) < slow + 5:
        return None
    f = close.rolling(fast).mean()
    l = close.rolling(slow).mean()
    above = (f > l).astype(int)
    flips = above.diff()
    flips = flips[flips != 0].dropna()
    last_cross = flips.index[-1] if len(flips) else None
    return {
        "bull": bool(above.iloc[-1]),
        "fast": float(f.iloc[-1]),
        "slow": float(l.iloc[-1]),
        "dist_pct": (float(f.iloc[-1]) / float(l.iloc[-1]) - 1) * 100,
        "last_cross": str(last_cross.date()) if last_cross is not None else None,
    }


def risk_split_vs_benchmark(df: pd.DataFrame, bench: pd.DataFrame) -> dict | None:
    """Descomposición de varianza del modelo de mercado: la parte exógena
    (sistemática) es β²·var(S&P)/var(activo) — el R² de la regresión
    diaria — y el resto es idiosincrática (propia del activo)."""
    joined = pd.concat(
        [df["Close"].pct_change(), bench["Close"].pct_change()], axis=1, join="inner"
    ).dropna()
    if len(joined) < 60:
        return None
    r, m = joined.iloc[:, 0], joined.iloc[:, 1]
    var_m, var_r = float(m.var()), float(r.var())
    if var_m == 0 or var_r == 0:
        return None
    beta = float(r.cov(m) / var_m)
    sys_share = min(max(beta * beta * var_m / var_r, 0.0), 1.0)
    return {"beta": beta, "systematic_pct": sys_share * 100, "idio_pct": (1 - sys_share) * 100, "days": len(joined)}


def signals_log_stats() -> dict | None:
    """Primer día registrado, conteo de señales y fecha estimada de la
    primera calificación oficial (10 barras de mercado después)."""
    if not SIGNALS_LOG_PATH.exists():
        return None
    try:
        lines = [json.loads(l) for l in SIGNALS_LOG_PATH.read_text().splitlines() if l.strip()]
        dates = sorted({e.get("market_date") or e.get("date") for e in lines if e.get("market_date") or e.get("date")})
        if not dates:
            return None
        first_grade = str(pd.bdate_range(start=dates[0], periods=11)[-1].date())
        return {"first": dates[0], "last": dates[-1], "count": len(lines), "days": len(dates), "first_grade": first_grade}
    except Exception:
        return None


CSS = """<style>
  :root { color-scheme: light;
    --bg:#f3f5f5; --panel:#ffffff; --panel2:#f6f8f8; --ink:#161b1e; --ink2:#4c565c; --ink3:#7d878e;
    --line:#dde3e5; --acc:#0e766e; --acc-ink:#0b5f59; --acc-soft:rgba(14,118,110,.09);
    --up:#1a7a4b; --down:#c2413f; --up-soft:rgba(26,122,75,.11); --down-soft:rgba(194,65,63,.10);
    --mono:ui-monospace,"SF Mono","Cascadia Mono","Roboto Mono",Consolas,monospace; }
  @media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { color-scheme: dark;
    --bg:#121517; --panel:#1a1e21; --panel2:#15181b; --ink:#e8eced; --ink2:#aab4b8; --ink3:#778187;
    --line:#2b3236; --acc:#3ab3a8; --acc-ink:#5cc6bc; --acc-soft:rgba(58,179,168,.13);
    --up:#46c584; --down:#e57171; --up-soft:rgba(70,197,132,.13); --down-soft:rgba(229,113,113,.12); } }
  :root[data-theme="dark"] { color-scheme: dark;
    --bg:#121517; --panel:#1a1e21; --panel2:#15181b; --ink:#e8eced; --ink2:#aab4b8; --ink3:#778187;
    --line:#2b3236; --acc:#3ab3a8; --acc-ink:#5cc6bc; --acc-soft:rgba(58,179,168,.13);
    --up:#46c584; --down:#e57171; --up-soft:rgba(70,197,132,.13); --down-soft:rgba(229,113,113,.12); }
  :root[data-theme="light"] { color-scheme: light;
    --bg:#f3f5f5; --panel:#ffffff; --panel2:#f6f8f8; --ink:#161b1e; --ink2:#4c565c; --ink3:#7d878e;
    --line:#dde3e5; --acc:#0e766e; --acc-ink:#0b5f59; --acc-soft:rgba(14,118,110,.09);
    --up:#1a7a4b; --down:#c2413f; --up-soft:rgba(26,122,75,.11); --down-soft:rgba(194,65,63,.10); }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink);
    font:14.5px/1.6 system-ui,"Segoe UI",Roboto,"Helvetica Neue",sans-serif; }
  main { max-width:980px; margin:0 auto; padding:38px 24px 72px; }
  .eyebrow { font-size:11.5px; letter-spacing:.18em; text-transform:uppercase; color:var(--ink3); margin:0 0 8px; font-family:var(--mono); }
  h1 { font-size:clamp(24px,4vw,32px); font-weight:800; letter-spacing:-.015em; margin:0 0 14px; text-wrap:balance; }
  .hmeta { display:flex; flex-wrap:wrap; gap:8px; margin-bottom:6px; }
  section { margin-top:36px; }
  .shead { display:flex; align-items:center; gap:14px; margin-bottom:14px; }
  .shead h2 { font-size:12.5px; letter-spacing:.16em; text-transform:uppercase; color:var(--ink2); margin:0; font-weight:700; }
  .shead::after { content:""; flex:1; height:1px; background:var(--line); }
  .lede { font-size:13px; color:var(--ink2); margin:0 0 14px; max-width:72ch; }
  .panel { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px 16px; }
  .tiles { display:grid; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); gap:10px; }
  .tile .k { font-size:10.5px; letter-spacing:.12em; text-transform:uppercase; color:var(--ink3); font-family:var(--mono); }
  .tile .v { font-size:20px; font-weight:750; margin:3px 0 2px; font-family:var(--mono); letter-spacing:-.01em; }
  .tile .sub { display:block; margin-bottom:8px; }
  .chip { display:inline-flex; align-items:center; gap:6px; border:1px solid var(--line); border-radius:999px;
    padding:2px 11px; font-family:var(--mono); font-size:11.5px; color:var(--ink2); background:var(--panel); }
  .chip.up { background:var(--up-soft); color:var(--up); border-color:transparent; }
  .chip.down { background:var(--down-soft); color:var(--down); border-color:transparent; }
  .chip.acc { background:var(--acc-soft); color:var(--acc-ink); border-color:transparent; }
  .chips { display:flex; flex-wrap:wrap; gap:6px; margin-bottom:10px; }
  details.dd { margin-top:6px; }
  details.dd > summary { list-style:none; cursor:pointer; color:var(--acc-ink); font-size:12px; font-weight:650;
    display:inline-flex; align-items:center; gap:6px; border-radius:4px; }
  details.dd > summary::-webkit-details-marker { display:none; }
  details.dd > summary::before { content:"\\25B8"; font-size:10px; }
  details.dd[open] > summary::before { content:"\\25BE"; }
  details.dd > summary:focus-visible { outline:2px solid var(--acc); outline-offset:2px; }
  .ddbody { margin-top:10px; padding:12px 14px; background:var(--panel2); border:1px solid var(--line);
    border-radius:8px; font-size:12.5px; color:var(--ink2); }
  .ddbody p { margin:0 0 8px; }
  .kv { width:100%; border-collapse:collapse; font-family:var(--mono); font-size:12px; margin:6px 0; }
  .kv th { font-size:10px; letter-spacing:.1em; text-transform:uppercase; color:var(--ink3); font-weight:600; }
  .kv td, .kv th { padding:4px 8px 4px 0; border-bottom:1px dashed var(--line); text-align:left; }
  .kv td.num, .kv th.num { text-align:right; font-variant-numeric:tabular-nums; }
  .src { margin:8px 0 0; padding-left:18px; }
  .src li { margin:3px 0; }
  .action { display:flex; gap:12px; align-items:flex-start; background:var(--panel); border:1px solid var(--line);
    border-radius:8px; padding:12px 14px; margin-bottom:8px; }
  .badge { font-family:var(--mono); font-size:11px; font-weight:700; letter-spacing:.06em; padding:2px 10px;
    border-radius:6px; background:var(--up-soft); color:var(--up); white-space:nowrap; margin-top:2px; }
  .action.vender .badge { background:var(--down-soft); color:var(--down); }
  .why { font-size:12.5px; color:var(--ink2); }
  .allclear { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px 16px; color:var(--ink2); }
  .lwrap { overflow-x:auto; }
  details.pos, details.watch { border:1px solid var(--line); border-radius:8px; background:var(--panel); margin-bottom:8px; min-width:740px; }
  .tile.key { border-color:var(--acc); }
  .tile.key .v { color:var(--acc-ink); }
  .decomp { margin-bottom:10px; }
  .decomp.book { border-color:var(--acc); }
  .drow { display:flex; align-items:center; gap:14px; margin-bottom:8px; flex-wrap:wrap; }
  .split { display:flex; height:10px; border-radius:5px; overflow:hidden; background:var(--panel2);
    border:1px solid var(--line); flex:1; min-width:150px; }
  .seg.exo { background:var(--ink3); }
  .seg.idio { background:var(--acc); }
  .splitv { font-family:var(--mono); font-size:12px; color:var(--ink2); white-space:nowrap; }
  .dcols { display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:8px 24px; }
  .dcols h4 { margin:0 0 4px; font-size:10.5px; letter-spacing:.12em; text-transform:uppercase;
    color:var(--ink3); font-family:var(--mono); font-weight:600; }
  .dcols .src { margin-top:0; font-size:12.5px; color:var(--ink2); }
  .legend { display:flex; flex-wrap:wrap; gap:16px; font-size:12px; color:var(--ink3); margin-bottom:10px; }
  .swatch { display:inline-block; width:10px; height:10px; border-radius:3px; margin-right:6px; }
  .swatch.exo { background:var(--ink3); }
  .swatch.idio { background:var(--acc); }
  details.pos > summary, details.watch > summary { display:grid; gap:10px; padding:12px 14px; cursor:pointer;
    align-items:center; list-style:none; }
  details.pos > summary { grid-template-columns:1.3fr .85fr 1.05fr .75fr 1fr .6fr 1.05fr; }
  details.watch > summary { grid-template-columns:1.5fr .9fr 1fr .8fr 1.3fr 1fr; }
  details.pos > summary::-webkit-details-marker, details.watch > summary::-webkit-details-marker { display:none; }
  details.pos > summary:focus-visible, details.watch > summary:focus-visible { outline:2px solid var(--acc); outline-offset:-2px; border-radius:8px; }
  details.pos[open], details.watch[open] { border-color:var(--acc); }
  .cell .k { font-size:10px; letter-spacing:.1em; text-transform:uppercase; color:var(--ink3); font-family:var(--mono); }
  .cell .v { font-family:var(--mono); font-size:13px; font-variant-numeric:tabular-nums; margin-top:1px; }
  .cell .v .sub { font-family:var(--mono); }
  .sym { font-weight:750; font-size:14.5px; }
  .up { color:var(--up); } .down { color:var(--down); }
  .posbody { border-top:1px solid var(--line); padding:12px 16px 14px; font-size:12.5px; color:var(--ink2); background:var(--panel2); border-radius:0 0 8px 8px; }
  .posbody .grid2 { display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:6px 22px; margin-bottom:6px; }
  .posbody .grid2 div { padding:2px 0; }
  .posbody b { color:var(--ink); font-weight:650; }
  .event { display:grid; grid-template-columns:118px 1fr; gap:14px; padding:12px 14px; border:1px solid var(--line);
    border-radius:8px; background:var(--panel); margin-bottom:8px; }
  .ewhen { font-family:var(--mono); font-size:12px; color:var(--acc-ink); font-weight:700; }
  .ewhen .sub { display:block; margin-top:2px; color:var(--ink3); font-weight:400; }
  .event h3 { margin:0 0 3px; font-size:14px; font-weight:700; }
  .enow { font-size:12.5px; color:var(--ink2); }
  .ethen { font-size:12.5px; color:var(--ink3); margin-top:4px; }
  .ethen b { color:var(--ink2); }
  .sub { font-size:11.5px; color:var(--ink3); }
  .valgrid { display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); gap:12px; }
  .valcard { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:14px 16px; }
  .valcard h3 { margin:0 0 8px; font-size:15px; }
  .chip2 { font-size:11.5px; font-family:var(--mono); padding:2px 9px; border-radius:6px; background:var(--acc-soft); color:var(--acc-ink); }
  .chip2.warn { background:var(--down-soft); color:var(--down); }
  .chip2.good { background:var(--up-soft); color:var(--up); font-weight:650; }
  .gcap { margin:10px 0 2px; }
  .pe-ref { stroke:var(--ink2); stroke-width:1.4; stroke-dasharray:6 4; }
  .pe-line { fill:none; stroke:var(--acc); stroke-width:2; stroke-linejoin:round; }
  .pe-dot { fill:var(--acc); }
  .pe-grid { stroke:var(--ink3); stroke-width:1; stroke-dasharray:3 4; opacity:.6; }
  .pe-label { fill:var(--ink3); font-size:10.5px; font-family:var(--mono); font-variant-numeric:tabular-nums; }
  .pe-label.strong { fill:var(--ink); font-weight:600; font-size:11.5px; }
  .pe-label.ref { fill:var(--ink2); font-weight:600; }
  .pe-label.halo { paint-order:stroke; stroke:var(--panel); stroke-width:3px; stroke-linejoin:round; }
  .pe-fwd { fill:var(--panel); stroke:var(--acc); stroke-width:1.8; }
  .pe-label.fwdlbl { fill:var(--acc-ink); font-weight:600; }
  .g-link { stroke:var(--ink3); stroke-width:2; }
  .g-link.up { stroke:var(--up); } .g-link.down { stroke:var(--down); }
  .g-old { fill:var(--panel); stroke:var(--ink3); stroke-width:1.5; }
  .g-new { fill:var(--ink2); } .g-new.up { fill:var(--up); } .g-new.down { fill:var(--down); }
  text.pe-label.up { fill:var(--up); } text.pe-label.down { fill:var(--down); }
  .zone-cheap { fill:var(--up-soft); }
  .zone-rich { fill:var(--down-soft); }
  svg { display:block; width:100%; height:auto; }
  .note { background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:13px 16px; color:var(--ink2); font-size:13px; margin-top:36px; }
</style>"""


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

    # --- shared fetch caches ---
    vreps: dict[str, dict] = {}

    def vrep_for(s: str) -> dict:
        if s not in vreps:
            try:
                vreps[s] = valuation_report(s)
            except Exception:
                vreps[s] = {}
        return vreps[s]

    def next_earnings(s: str) -> str | None:
        try:
            dates = get_calendar_events(s).get("earnings_dates") or []
        except Exception:
            return None
        return next((d for d in dates if d >= as_of), dates[-1] if dates else None)

    # --- per-position monitoring rows ---
    sp_df = dfs.get("^GSPC")
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
        ret = df["Close"].pct_change().dropna()
        sigma20 = float(ret.tail(20).std(ddof=0)) * 100
        sigma100 = float(ret.tail(100).std(ddof=0)) * 100
        stop_level = p["entry_price"] * (1 - DEFAULT_STOP_LOSS_PCT / 100)
        is_stock = infer_asset_class(s) is AssetClass.STOCK
        pe = vrep_for(s).get("trailing_pe") if is_stock else None
        rows.append({
            "symbol": s, "weight": p["weight"], "entry_price": p["entry_price"], "entry_date": p["entry_date"],
            "conf_at_selection": p.get("confidence_at_selection"),
            "price": price, "pnl_pct": pnl, "signal": rec["overall_action"], "signal_conf": rec["confidence_pct"],
            "exposure_pct": exposure, "sigma20": sigma20, "sigma100": sigma100,
            "stop_level": stop_level, "pe": pe, "is_stock": is_stock,
            "stop_distance_pct": (price / stop_level - 1) * 100,
            "next_earnings": next_earnings(s) if is_stock else None,
            "beta": beta_vs_benchmark(df, sp_df) if sp_df is not None else None,
        })
    rows.sort(key=lambda r: -r["weight"])

    # --- key indicator: implied expected return (earnings yield + beta) ---
    market_pe, market_pe_kind = proxy_pe("SPY")
    market_ey = 1.0 / market_pe if market_pe else None
    ey_pond, beta_pond, ey_available = 0.0, 0.0, False
    for r in rows:
        if r["is_stock"]:
            vrep = vrep_for(r["symbol"])
            pe_used = vrep.get("implicit_forward_pe") or vrep.get("trailing_pe")
            pe_src = "fwd implícito (consenso +1y)" if vrep.get("implicit_forward_pe") else "P/E actual"
        else:
            proxy = INDEX_PE_PROXY.get(r["symbol"])
            pe_used, kind = proxy_pe(proxy)
            pe_src = f"proxy {proxy} ({kind})" if pe_used else None
        if pe_used:
            ey = 1.0 / pe_used
        elif r["beta"] is not None and market_ey:
            ey = r["beta"] * market_ey
            pe_src = "β × implícito S&P (sin P/E propio)"
        else:
            ey, pe_src = None, "sin datos"
        r["ey"], r["pe_used"], r["pe_src"] = ey, pe_used, pe_src
        if ey is not None:
            ey_pond += r["weight"] * ey
            ey_available = True
        if r["beta"] is not None:
            beta_pond += r["weight"] * r["beta"]
    capm_ret = beta_pond * market_ey if market_ey else None

    # --- idiosyncratic vs exogenous decomposition per position + book ---
    for r in rows:
        df = dfs[r["symbol"]]
        r["split"] = risk_split_vs_benchmark(df, sp_df) if sp_df is not None else None
        r["cross"] = sma_cross_state(df)
        r["alpha_imp_pp"] = (
            (r["ey"] - r["beta"] * market_ey) * 100
            if r["ey"] is not None and r["beta"] is not None and market_ey
            else None
        )
        if r["is_stock"]:
            rel = sector_relative_valuation(r["symbol"], r["pe"])
            r["rel_reading"], r["rel_ratio"] = rel.get("reading"), rel.get("ratio")
        else:
            r["rel_reading"], r["rel_ratio"] = None, None
    book_split = None
    invested = {r["symbol"]: r["weight"] for r in rows}
    total_w = sum(invested.values())
    if total_w > 0 and sp_df is not None and rows:
        rets = pd.concat(
            [dfs[s]["Close"].pct_change().rename(s) for s in invested], axis=1, join="inner"
        ).dropna()
        port_ret = sum(rets[s] * (w / total_w) for s, w in invested.items())
        pseudo = pd.DataFrame({"Close": (1 + port_ret).cumprod()})
        book_split = risk_split_vs_benchmark(pseudo, sp_df.loc[pseudo.index[0]:])

    # --- watchlist: universe stocks outside the book ---
    held = set(state["positions"])
    watch = []
    for s, df in dfs.items():
        if infer_asset_class(s) is not AssetClass.STOCK or s in held:
            continue
        rec = recommend(df, symbol=s, initial_capital=NOMINAL_CAPITAL, commission_bps=None, allow_short=False)
        vrep = vrep_for(s)
        rel = sector_relative_valuation(s, vrep.get("trailing_pe"))
        guidance_txt = {"bullish": "revisiones al alza", "bearish": "revisiones a la baja", "neutral": "revisiones estables"}.get(
            vrep.get("guidance_signal", "neutral"), "sin lectura"
        )
        watch.append({
            "symbol": s,
            "price": float(df["Close"].iloc[-1]),
            "signal": rec["overall_action"],
            "signal_conf": rec["confidence_pct"],
            "pe": vrep.get("trailing_pe"),
            "fwd": vrep.get("implicit_forward_pe"),
            "industry": rel.get("industry") or rel.get("sector") or "",
            "reading": rel.get("reading", "sin referencia"),
            "ratio": rel.get("ratio"),
            "reference_pe": rel.get("reference_pe"),
            "guidance_txt": guidance_txt,
            "next_earnings": next_earnings(s),
        })
    order = {"BUY": 0, "HOLD": 1, "SELL": 2}
    watch.sort(key=lambda w: (order.get(w["signal"], 3), -w["signal_conf"]))

    # --- regime detail (S&P vs its 200-day SMA) ---
    regime_detail = None
    sp = dfs.get("^GSPC")
    if sp is not None and len(sp) >= 200:
        sma200 = float(sp["Close"].rolling(200).mean().iloc[-1])
        sp_close = float(sp["Close"].iloc[-1])
        regime_detail = {"close": sp_close, "sma200": sma200, "dist_pct": (sp_close / sma200 - 1) * 100}

    # --- fundamental valuation cards for stock positions ---
    valuation_cards = []
    for r in rows:
        s = r["symbol"]
        if not r["is_stock"] or s not in dfs:
            continue
        vrep = vrep_for(s)
        guidance_txt = {"bullish": "revisiones al alza", "bearish": "revisiones a la baja", "neutral": "revisiones estables"}.get(
            vrep.get("guidance_signal", "neutral"), "sin lectura"
        )
        rel = sector_relative_valuation(s, vrep.get("trailing_pe"))
        valuation_cards.append({
            "symbol": s,
            "trailing_pe": vrep.get("trailing_pe"),
            "implicit_forward_pe": vrep.get("implicit_forward_pe"),
            "trailing_eps": vrep.get("trailing_eps"),
            "estimates": vrep.get("estimates") or {},
            "guidance_txt": guidance_txt,
            "guidance_signal": vrep.get("guidance_signal", "neutral"),
            "industry": rel.get("industry") or rel.get("sector") or "",
            "relative_reading": rel.get("reading", "sin referencia"),
            "relative_ratio": rel.get("ratio"),
            "reference_pe": rel.get("reference_pe"),
            "edgar": edgar_ttm_detail(s, as_of),
            "price": r["price"],
            "svg": pe_svg(pe_history_series(s, dfs[s]), rel.get("reference_pe"), vrep.get("implicit_forward_pe")),
            "guidance_svg": guidance_svg(vrep.get("estimates") or {}, vrep.get("trailing_eps")),
        })

    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n")

    # --- event radar ---
    log_stats = signals_log_stats()
    events = []
    for r in sorted((r for r in rows if r.get("next_earnings")), key=lambda r: r["next_earnings"]):
        events.append({
            "when": fmt_date(r["next_earnings"]), "kind": "posición", "sort": r["next_earnings"],
            "title": f"Resultados trimestrales de {r['symbol']}",
            "now": f"P/E actual {r['pe']:.1f}" + (f" · señal {r['signal']} {r['signal_conf']:.0f}%" if r.get("signal") else ""),
            "then": "El EPS reportado actualiza el P/E punto-en-tiempo (EDGAR) y el consenso de guidance; "
                    "una sorpresa fuerte puede mover la señal de valuación y la confianza en la próxima re-selección.",
        })
    for w in (w for w in watch if w.get("next_earnings")):
        events.append({
            "when": fmt_date(w["next_earnings"]), "kind": "watchlist", "sort": w["next_earnings"],
            "title": f"Resultados trimestrales de {w['symbol']}",
            "now": (f"P/E actual {w['pe']:.1f} · " if w.get("pe") else "") + f"señal {w['signal']} {w['signal_conf']:.0f}%",
            "then": "Cambia su caso para entrar al libro: EPS nuevo → P/E y tilt nuevos con los que compite en la re-selección.",
        })
    if log_stats:
        events.append({
            "when": f"~{fmt_date(log_stats['first_grade'])}", "kind": "evidencia", "sort": log_stats["first_grade"],
            "title": "Primera calificación oficial del registro de señales",
            "now": f"{log_stats['count']} señales registradas en {log_stats['days']} días de mercado (desde {fmt_date(log_stats['first'])})",
            "then": "Las señales del primer día cumplen 10 barras: `track report` produce el primer hit-rate "
                    "hacia adelante — la única evidencia sin retrovisor. Si contradice a los backtests, manda ella.",
        })
    events.append({
        "when": fmt_date(state["next_rebalance"]), "kind": "programado", "sort": state["next_rebalance"],
        "title": "Re-selección trimestral del libro",
        "now": f"{len(rows)} posiciones + {state['cash_weight']*100:.1f}% efectivo esperando",
        "then": "Se recalcula todo: lectura de régimen → universo → selección por confianza ajustada "
                "(técnica + tilt de P/E) → pesos por risk parity. <b>Única puerta de entrada de la watchlist al libro.</b>",
    })
    events.sort(key=lambda e: e["sort"])
    # level-triggered watches (no date — they can fire any day)
    sells = [r for r in rows if r["signal"] == "SELL"]
    nearest = min(rows, key=lambda r: r["stop_distance_pct"]) if rows else None
    level_events = []
    if nearest:
        level_events.append({
            "when": "nivel", "kind": "cualquier día",
            "title": f"Stop-loss (−{DEFAULT_STOP_LOSS_PCT:.0f}% desde la entrada)",
            "now": f"La más cercana: {nearest['symbol']} a {nearest['stop_distance_pct']:.1f}% de su nivel ({nearest['stop_level']:,.2f})",
            "then": "Cruzar el nivel genera la orden de salida a efectivo al día siguiente; el efectivo espera a la re-selección.",
        })
    level_events.append({
        "when": "diario", "kind": "cualquier día",
        "title": "Señal SELL ≥55% en una posición",
        "now": ("Hoy: " + ", ".join(f"{r['symbol']} {r['signal']} {r['signal_conf']:.0f}%" for r in rows)) if rows else "Sin posiciones",
        "then": "Un SELL del ensemble con confianza ≥55% saca la posición a efectivo al día siguiente, sin esperar el corte trimestral."
                + (f" <b>Atención: {', '.join(r['symbol'] for r in sells)} ya está en SELL.</b>" if sells else ""),
    })
    if regime_detail:
        level_events.append({
            "when": "nivel", "kind": "cualquier día",
            "title": "S&P 500 contra su media de 200 días",
            "now": f"Cierre {regime_detail['close']:,.0f} vs SMA200 {regime_detail['sma200']:,.0f} ({regime_detail['dist_pct']:+.1f}%)",
            "then": "Un cruce por debajo apaga el régimen alcista: la <b>próxima</b> re-selección vuelve al universo "
                    "defensivo completo (cripto/FX/commodities, tope 2 por clase). No corta el trimestre en curso — "
                    "la frontera de emergencia se probó dos veces y perdió.",
        })

    # --- render helpers ---
    regime_txt = "ALCISTA" if state["regime_risk_on"] else ("DEFENSIVO" if state["regime_risk_on"] is False else "SIN LECTURA")
    regime_sub = "100% acciones e índices" if state["regime_risk_on"] else ("universo completo, tope 2 por clase" if state["regime_risk_on"] is False else "")

    def money(w):
        return f"${w*NOMINAL_CAPITAL:,.0f}"

    def dd(summary: str, body: str) -> str:
        return f"<details class='dd'><summary>{summary}</summary><div class='ddbody'>{body}</div></details>"

    PRICE_SRC = "Precios: cierres diarios ajustados, Yahoo Finance chart API (respaldo automático: Stooq)."
    SIGNAL_SRC = "Señal: ensemble de 5 estrategias técnicas (SMA/EMA/RSI/MACD/tendencia) ponderadas por régimen ADX."

    def pos_html(r: dict) -> str:
        pnl_cls = "up" if r["pnl_pct"] >= 0 else "down"
        sig_cls = "up" if r["signal"] == "BUY" else ("down" if r["signal"] == "SELL" else "")
        pe_txt = f"{r['pe']:.1f}" if r.get("pe") else "—"
        earn = f"<div><b>Próximo reporte:</b> {fmt_date(r['next_earnings'])}</div>" if r.get("next_earnings") else ""
        conf_sel = f" · confianza {r['conf_at_selection']}% al seleccionarla" if r.get("conf_at_selection") else ""
        sources = (
            f"<ul class='src'><li>{PRICE_SRC}</li><li>{SIGNAL_SRC}</li>"
            + (f"<li>P/E: precio actual entre EPS de los últimos 4 trimestres presentados a la SEC (EDGAR, ajustado por splits) — drill-down completo en su tarjeta de valuación.</li>" if r["is_stock"] else "<li>P/E: no aplica — un índice no tiene utilidades por acción propias.</li>")
            + "<li>Libro: portfolio_state.json (papel, $10,000 nominales), versionado en el repositorio.</li></ul>"
        )
        beta_txt = f"{r['beta']:.2f}" if r.get("beta") is not None else "—"
        beta_read = ""
        if r.get("beta") is not None:
            beta_read = (
                "se mueve casi 1:1 con el índice" if 0.85 <= r["beta"] <= 1.15
                else ("amplifica los movimientos del índice" if r["beta"] > 1.15 else "amortigua los movimientos del índice")
            )
            beta_read = f"<div><b>β vs S&amp;P:</b> {r['beta']:.2f} — {beta_read} (retornos diarios, ~3 años)</div>"
        body = (
            f"<div class='grid2'>"
            f"<div><b>Entrada:</b> {r['entry_price']:,.2f} el {fmt_date(r['entry_date'])}{conf_sel}</div>"
            f"<div><b>P&amp;L:</b> {r['price']:,.2f} / {r['entry_price']:,.2f} − 1 = <span class='{pnl_cls}'>{r['pnl_pct']:+.2f}%</span></div>"
            f"<div><b>Peso:</b> {r['weight']*100:.1f}% ({money(r['weight'])}) — inverso a su volatilidad (risk parity)</div>"
            f"<div><b>Exposición vol.:</b> σ20d {r['sigma20']:.2f}% vs σ100d {r['sigma100']:.2f}% diaria → {r['exposure_pct']:.0f}% del tamaño (piso 25%)</div>"
            f"<div><b>Stop-loss:</b> {r['entry_price']:,.2f} × 0.85 = {r['stop_level']:,.2f} — hoy a {r['stop_distance_pct']:.1f}%</div>"
            f"<div><b>Señal hoy:</b> {r['signal']} con {r['signal_conf']:.0f}% — un SELL ≥55% la saca a efectivo</div>"
            f"{beta_read}"
            f"{earn}"
            f"</div>{sources}"
        )
        return (
            f"<details class='pos'><summary>"
            f"<div class='cell'><span class='sym'>{r['symbol']}</span><div class='sub'>desde {fmt_date(r['entry_date'])}</div></div>"
            f"<div class='cell'><div class='k'>Peso</div><div class='v'>{r['weight']*100:.1f}%<span class='sub'> {money(r['weight'])}</span></div></div>"
            f"<div class='cell'><div class='k'>Actual / entrada</div><div class='v'>{r['price']:,.2f}<span class='sub'> / {r['entry_price']:,.2f}</span></div></div>"
            f"<div class='cell'><div class='k'>P&amp;L</div><div class='v {pnl_cls}'>{r['pnl_pct']:+.2f}%</div></div>"
            f"<div class='cell'><div class='k'>Señal · P/E</div><div class='v {sig_cls}'>{r['signal']} {r['signal_conf']:.0f}%<span class='sub'> · {pe_txt}</span></div></div>"
            f"<div class='cell'><div class='k'>β vs S&amp;P</div><div class='v'>{beta_txt}</div></div>"
            f"<div class='cell'><div class='k'>Stop-loss</div><div class='v'>{r['stop_level']:,.2f}<span class='sub'> a {r['stop_distance_pct']:.1f}%</span></div></div>"
            f"</summary><div class='posbody'>{body}</div></details>"
        )

    def watch_html(w: dict) -> str:
        sig_cls = "up" if w["signal"] == "BUY" else ("down" if w["signal"] == "SELL" else "")
        pe_txt = f"{w['pe']:.1f}" if w.get("pe") else "—"
        ratio_txt = f"{w['ratio']:.2f}x" if w.get("ratio") else "—"
        rel_cls = "up" if "barata" in w["reading"] else ("down" if "cara" in w["reading"] else "")
        earn_txt = fmt_date(w["next_earnings"]) if w.get("next_earnings") else "—"
        fwd_txt = f"{w['fwd']:.1f}" if w.get("fwd") else "—"
        ratio_math = (
            f"<div><b>Vs industria:</b> {w['pe']:.1f} / {w['reference_pe']:.0f} (mediana {w['industry']}) = {w['ratio']:.2f}x → {w['reading']}</div>"
            if w.get("ratio") and w.get("reference_pe") and w.get("pe") else ""
        )
        body = (
            f"<div class='grid2'>"
            f"<div><b>Señal hoy:</b> {w['signal']} con {w['signal_conf']:.0f}% (ensemble técnico)</div>"
            f"<div><b>Valuación:</b> P/E {pe_txt} · fwd implícito {fwd_txt} · guidance: {w['guidance_txt']}</div>"
            f"{ratio_math}"
            + (f"<div><b>Próximo reporte:</b> {fmt_date(w['next_earnings'])}</div>" if w.get("next_earnings") else "")
            + f"</div>"
            f"<p><b>Cómo entra al libro:</b> compite en la re-selección del {fmt_date(state['next_rebalance'])} por confianza "
            f"ajustada (técnica + tilt de P/E). En la selección vigente el tope de 2 acciones por clase dejó dentro a las de mayor "
            f"confianza ajustada; no hay entradas a mitad de trimestre (el redespliegue inmediato se validó y rechazó).</p>"
            f"<ul class='src'><li>{PRICE_SRC}</li><li>{SIGNAL_SRC}</li>"
            f"<li>Valuación: Yahoo quoteSummary (P/E, estimados de analistas, calendario de resultados); mediana de industria: tabla fija en app/fundamentals/sector_pe.py.</li></ul>"
        )
        return (
            f"<details class='watch'><summary>"
            f"<div class='cell'><span class='sym'>{w['symbol']}</span><div class='sub'>{w['industry']}</div></div>"
            f"<div class='cell'><div class='k'>Precio</div><div class='v'>{w['price']:,.2f}</div></div>"
            f"<div class='cell'><div class='k'>Señal hoy</div><div class='v {sig_cls}'>{w['signal']} {w['signal_conf']:.0f}%</div></div>"
            f"<div class='cell'><div class='k'>P/E</div><div class='v'>{pe_txt}</div></div>"
            f"<div class='cell'><div class='k'>Vs industria</div><div class='v {rel_cls}'>{ratio_txt}<span class='sub'> {w['reading'].replace(' para su industria','').replace(' con su industria','')}</span></div></div>"
            f"<div class='cell'><div class='k'>Próx. reporte</div><div class='v'>{earn_txt}</div></div>"
            f"</summary><div class='posbody'>{body}</div></details>"
        )

    def split_bar(split: dict | None) -> str:
        if not split:
            return "<span class='sub'>sin datos</span>"
        return (
            f"<div class='split'><div class='seg exo' style='width:{split['systematic_pct']:.0f}%'></div>"
            f"<div class='seg idio' style='width:{split['idio_pct']:.0f}%'></div></div>"
            f"<span class='v splitv'>{split['systematic_pct']:.0f}% / {split['idio_pct']:.0f}%</span>"
        )

    def decomp_html(r: dict) -> str:
        split, cross = r.get("split"), r.get("cross")
        exo_items = []
        if r.get("beta") is not None:
            exo_items.append(f"β {r['beta']:.2f}: cada 1% del S&amp;P la mueve ~{r['beta']:.2f}%")
        if regime_detail:
            exo_items.append(
                f"régimen de mercado {regime_txt} — S&amp;P {regime_detail['dist_pct']:+.1f}% sobre su SMA200 (señal compartida por todo el libro)"
            )
        if r.get("beta") is not None and market_ey:
            exo_items.append(f"rendimiento explicado por mercado: β × implícito S&amp;P = {r['beta']:.2f} × {market_ey*100:.1f}% = {r['beta']*market_ey*100:.1f}% anual")
        idio_items = []
        if cross:
            lado = "alcista" if cross["bull"] else "bajista"
            desde = f" desde {fmt_date(cross['last_cross'])}" if cross.get("last_cross") else ""
            idio_items.append(
                f"cruce SMA20/50 propio: <b>{lado}</b>{desde} (media rápida {cross['dist_pct']:+.1f}% vs lenta) — la señal de la estrategia original sobre su propia serie"
            )
        if r.get("rel_ratio"):
            idio_items.append(f"valuación propia: {r['rel_ratio']:.2f}x la mediana de su industria → {r['rel_reading']}")
        elif not r["is_stock"]:
            idio_items.append("valuación propia: n/a — es un índice; su múltiplo se lee vía ETF réplica en el resumen")
        if r.get("alpha_imp_pp") is not None:
            sign_cls = "up" if r["alpha_imp_pp"] >= 0 else "down"
            idio_items.append(
                f"alpha implícito por valuación: E/P − β·S&amp;P = <span class='{sign_cls}'>{r['alpha_imp_pp']:+.1f} pp</span> anual"
            )
        exo_li = "".join(f"<li>{x}</li>" for x in exo_items) or "<li>sin datos</li>"
        idio_li = "".join(f"<li>{x}</li>" for x in idio_items) or "<li>sin datos</li>"
        days = f" ({split['days']} días comunes)" if split else ""
        detail = dd(
            "fuente y cálculo",
            f"<p><b>Parte exógena (R²)</b> = β²·var(S&amp;P) / var(activo), retornos diarios ~3 años{days}. "
            f"Lo que no explica el mercado es idiosincrático. El alpha implícito compara el rendimiento por P/E del "
            f"activo (E/P) contra lo que su β exigiría del S&amp;P — positivo = pagas menos múltiplo del que su riesgo "
            f"sistemático justificaría.</p>"
            f"<ul class='src'><li>{PRICE_SRC}</li><li>Cruce SMA20/50: SmaCrossoverStrategy, las mismas ventanas de la estrategia original.</li>"
            f"<li>E/P y β: los mismos del indicador de rendimiento implícito del resumen.</li></ul>",
        )
        return (
            f"<div class='panel decomp'>"
            f"<div class='drow'><span class='sym'>{r['symbol']}</span>{split_bar(split)}</div>"
            f"<div class='dcols'><div><h4>Exógeno (mercado)</h4><ul class='src'>{exo_li}</ul></div>"
            f"<div><h4>Idiosincrático (propio)</h4><ul class='src'>{idio_li}</ul></div></div>"
            f"{detail}</div>"
        )

    def event_html(e: dict) -> str:
        return (
            f"<div class='event'><div class='ewhen'>{e['when']}<span class='sub'>{e['kind']}</span></div>"
            f"<div><h3>{e['title']}</h3><div class='enow'>{e['now']}</div>"
            f"<div class='ethen'>Si ocurre: {e['then']}</div></div></div>"
        )

    def valcard_html(c: dict) -> str:
        tr = f"{c['trailing_pe']:.1f}" if c.get("trailing_pe") else "—"
        fw = f"{c['implicit_forward_pe']:.1f}" if c.get("implicit_forward_pe") else "—"
        warn = " warn" if c["guidance_signal"] == "bearish" else ""
        ratio_txt = f" ({c['relative_ratio']:.2f}x)" if c.get("relative_ratio") else ""
        rel_cls = " good" if "barata" in c["relative_reading"] else (" warn" if "cara" in c["relative_reading"] else "")
        ref_chip = (
            f"<span class='chip2'>P/E industria {c['reference_pe']:.0f}</span>" if c.get("reference_pe") else ""
        )
        edgar = c.get("edgar")
        if edgar:
            qrows = "".join(
                f"<tr><td>{fmt_date(q['end'])}</td><td>{fmt_date(q['filed'])}</td><td class='num'>{q['eps']:.2f}</td></tr>"
                for q in edgar["quarters"]
            )
            splits_note = (
                f"EPS reexpresado a unidades de hoy dividiendo entre los splits posteriores a cada trimestre ({edgar['num_splits']} splits en el historial del símbolo). "
                if edgar["num_splits"] else ""
            )
            pe_math = (
                f"<p><b>P/E actual = precio / EPS 12m:</b> {c['price']:,.2f} / {edgar['ttm']:.2f} = {c['price']/edgar['ttm']:.1f}</p>"
                if edgar["ttm"] > 0 else ""
            )
            edgar_dd = dd(
                "fuente y cálculo del P/E",
                f"<p>Los 4 trimestres presentados a la SEC que sustentan el EPS de 12 meses — la columna "
                f"<b>presentado</b> es la compuerta causal: un dato solo cuenta desde que su reporte fue público.</p>"
                f"<table class='kv'><tr><th>Trimestre (fin)</th><th>Presentado</th><th class='num'>EPS dil.</th></tr>{qrows}"
                f"<tr><td colspan='2'><b>EPS 12 meses</b></td><td class='num'><b>{edgar['ttm']:.2f}</b></td></tr></table>"
                f"{pe_math}"
                f"<p>{splits_note}La serie histórica del gráfico aplica esta misma regla día por día.</p>"
                f"<ul class='src'><li>EPS trimestral: SEC EDGAR companyfacts (XBRL), con fecha de presentación.</li>"
                f"<li>Splits: eventos del chart API de Yahoo.</li>"
                f"<li>Estimados y guidance: Yahoo quoteSummary (earningsTrend) — consenso de analistas hoy y hace 90 días.</li>"
                f"<li>Mediana de industria: tabla fija (estilo Damodaran) en app/fundamentals/sector_pe.py — no ajustada a backtests.</li></ul>",
            )
        else:
            edgar_dd = ""
        return (
            f"<div class='valcard'><h3>{c['symbol']} <span class='sub'>{c['industry']}</span></h3>"
            f"<div class='chips'><span class='chip2'>P/E actual {tr}</span>"
            f"{ref_chip}"
            f"<span class='chip2'>fwd implícito {fw}</span>"
            f"<span class='chip2{warn}'>guidance: {c['guidance_txt']}</span>"
            f"<span class='chip2{rel_cls}'>vs industria: {c['relative_reading']}{ratio_txt}</span></div>"
            f"{c['svg']}"
            f"<div class='sub gcap'>Guidance: EPS consenso, hace 90 días (hueco) → hoy (sólido)</div>"
            f"{c['guidance_svg']}"
            f"{edgar_dd}</div>"
        )

    # --- assemble sections ---
    action_html = "".join(
        f"<div class='action {a['tipo'].lower()}'><span class='badge'>{a['tipo']}</span>"
        f"<div><strong>{a['symbol']}</strong> — {a['detalle']}<div class='why'>{a['motivo']}</div></div></div>"
        for a in actions
    ) or "<p class='allclear'>Sin movimientos hoy: todas las posiciones conservan su señal, ningún stop-loss disparado y la próxima re-selección no ha llegado.</p>"

    regime_dd = ""
    if regime_detail:
        regime_dd = dd(
            "fuente y cálculo",
            f"<p><b>Regla:</b> S&amp;P 500 sobre su media móvil de 200 días → régimen alcista (universo restringido a "
            f"acciones e índices, sin tope de clase). Hoy: cierre {regime_detail['close']:,.2f} vs SMA200 "
            f"{regime_detail['sma200']:,.2f} → <b>{regime_detail['dist_pct']:+.1f}%</b>.</p>"
            f"<ul class='src'><li>{PRICE_SRC}</li>"
            f"<li>Validación: 6/9 ventanas sobre el modelo sin tilt y 8/9 contra el S&amp;P (validate_equity_tilt_result.json).</li></ul>",
        )
    book_dd = dd(
        "fuente y cálculo",
        f"<p>Pesos por <b>risk parity</b>: cada posición pesa el inverso de su volatilidad reciente, normalizado. "
        f"El efectivo es lo no asignado; el liberado por ventas espera al corte trimestral.</p>"
        f"<ul class='src'><li>Libro: portfolio_state.json (papel, $10,000 nominales), versionado en el repositorio.</li></ul>",
    )
    last_selection = max((p["entry_date"] for p in state["positions"].values()), default=state.get("created", as_of))
    reb_dd = dd(
        "fuente y cálculo",
        f"<p><b>Regla:</b> re-selección cada {REBALANCE_MONTHS} meses desde la última ({fmt_date(last_selection)} → {fmt_date(state['next_rebalance'])}), "
        f"o salida anticipada de una posición individual por SELL ≥55% / stop-loss (sin re-entrada hasta el corte).</p>"
        f"<ul class='src'><li>Validación del trimestre: 7/9 contra no rebalancear; el barrido de robustez aprobó 3/6/12 meses y reprobó 1 mes (validate_rebalance_result.json).</li></ul>",
    )

    # key-indicator tile (implied return + weighted beta) with full arithmetic drilldown
    def _f(v, fmt=".2f"):
        return format(v, fmt) if v is not None else "—"

    imp_table_rows = "".join(
        f"<tr><td>{r['symbol']}</td><td class='num'>{r['weight']*100:.1f}%</td>"
        f"<td class='num'>{_f(r['pe_used'], '.1f')}</td><td>{r['pe_src']}</td>"
        f"<td class='num'>{_f(r['ey']*100 if r['ey'] is not None else None, '.1f')}%</td>"
        f"<td class='num'>{_f(r['beta'])}</td>"
        f"<td class='num'>{_f(r['weight']*r['ey']*100 if r['ey'] is not None else None, '.2f')}%</td></tr>"
        for r in rows
    )
    cash_row = (
        f"<tr><td>Efectivo</td><td class='num'>{state['cash_weight']*100:.1f}%</td><td class='num'>—</td>"
        f"<td>no invertido</td><td class='num'>0.0%</td><td class='num'>0.00</td><td class='num'>0.00%</td></tr>"
    )
    market_line = (
        f"<p><b>Benchmark:</b> S&amp;P 500 vía SPY ({market_pe_kind}): P/E {market_pe:.1f} → rendimiento implícito {market_ey*100:.1f}% anual.</p>"
        if market_ey else "<p><b>Benchmark:</b> sin lectura de P/E del S&amp;P hoy (SPY no disponible).</p>"
    )
    capm_line = (
        f"<p><b>Verificación CAPM:</b> β ponderada × implícito del S&amp;P = {beta_pond:.2f} × {market_ey*100:.1f}% = <b>{capm_ret*100:.1f}% anual</b>.</p>"
        if capm_ret is not None else ""
    )
    imp_dd = dd(
        "fuente y cálculo",
        f"<p><b>Rendimiento implícito por P/E</b> = Σ peso × (1 / P/E): pagar {(1/ey_pond if ey_available and ey_pond else 0):.1f}x utilidades equivale a "
        f"un rendimiento de utilidades del {ey_pond*100:.1f}% anual si el múltiplo se sostiene.</p>"
        f"<table class='kv'><tr><th>Símbolo</th><th class='num'>Peso</th><th class='num'>P/E usado</th><th>Fuente del P/E</th>"
        f"<th class='num'>E/P anual</th><th class='num'>β vs S&amp;P</th><th class='num'>Aporte w·E/P</th></tr>"
        f"{imp_table_rows}{cash_row}"
        f"<tr><td><b>Libro</b></td><td class='num'><b>100%</b></td><td class='num'></td><td></td>"
        f"<td class='num'><b>{ey_pond*100:.1f}%</b></td><td class='num'><b>{beta_pond:.2f}</b></td><td class='num'><b>{ey_pond*100:.1f}%</b></td></tr></table>"
        f"{market_line}{capm_line}"
        f"<p><b>β por acción:</b> covarianza de retornos diarios contra el S&amp;P 500 entre la varianza del S&amp;P, "
        f"~3 años de historia común; la ponderada suma peso × β (el efectivo pondera β 0).</p>"
        f"<ul class='src'><li>P/E de acciones: consenso de analistas (Yahoo earningsTrend) — forward implícito; respaldo: P/E actual.</li>"
        f"<li>P/E de índices: su ETF réplica (SPY/DIA/QQQ) vía Yahoo quoteSummary.</li>"
        f"<li>Retornos para β: cierres diarios ajustados (Yahoo chart API, respaldo Stooq).</li></ul>"
        f"<p>Indicador informativo: el earnings yield es el rendimiento de largo plazo implícito en el múltiplo, no una promesa a 12 meses, "
        f"y supone múltiplo y utilidades sostenidos. No entra al modelo ni está validado en las 9 ventanas.</p>",
    )
    imp_value = f"{ey_pond*100:.1f}% anual" if ey_available else "—"
    imp_sub = (
        f"β ponderada {beta_pond:.2f} vs S&amp;P" + (f" · vía CAPM {capm_ret*100:.1f}%" if capm_ret is not None else "")
        if rows else "libro sin posiciones"
    )
    key_tile = (
        f"<div class='tile panel key'><div class='k'>Rendimiento implícito esperado</div>"
        f"<div class='v'>{imp_value}</div><span class='sub'>{imp_sub}</span>{imp_dd}</div>"
    )

    pos_footer = (
        f"<div class='chips' style='margin-top:2px'>"
        f"<span class='chip acc'>β ponderada del libro {beta_pond:.2f} vs S&amp;P</span>"
        f"<span class='chip'>rendimiento implícito {ey_pond*100:.1f}% anual</span></div>"
        if rows else ""
    )
    pos_section = ("<div class='lwrap'>" + "".join(pos_html(r) for r in rows) + "</div>" + pos_footer) if rows else "<p class='allclear'>Libro sin posiciones — todo en efectivo hasta la próxima re-selección.</p>"
    watch_section = "<div class='lwrap'>" + "".join(watch_html(w) for w in watch) + "</div>" if watch else "<p class='allclear'>Sin candidatas fuera del libro.</p>"
    events_section = "".join(event_html(e) for e in events) + "".join(event_html(e) for e in level_events)

    valuation_html = (
        "<div class='valgrid'>" + "".join(valcard_html(c) for c in valuation_cards) + "</div>"
        if valuation_cards
        else "<p class='allclear'>El libro actual no tiene acciones individuales — los índices no tienen P/E por símbolo.</p>"
    )

    # idiosyncratic vs exogenous section
    legend = (
        "<div class='legend'><span><span class='swatch exo'></span>exógeno — lo que explica el S&amp;P 500</span>"
        "<span><span class='swatch idio'></span>idiosincrático — lo propio del activo</span></div>"
    )
    book_line = ""
    if book_split:
        book_line = (
            f"<div class='panel decomp book'><div class='drow'><span class='sym'>Libro completo</span>{split_bar(book_split)}</div>"
            f"<p class='enow'>Con β ponderada {beta_pond:.2f} y {book_split['systematic_pct']:.0f}% de la varianza explicada por el índice, "
            f"el resultado del libro lo decide sobre todo el <b>mercado</b> (componente exógeno: régimen y β). El "
            f"{book_split['idio_pct']:.0f}% restante es <b>selección</b>: qué acciones, a qué múltiplo y con qué señal propia.</p></div>"
        )
    decomp_section = legend + book_line + "".join(decomp_html(r) for r in rows) if rows else "<p class='allclear'>Libro sin posiciones.</p>"

    sources_html = (
        "<div class='panel'><ul class='src' style='margin-top:0'>"
        "<li><b>Precios:</b> Yahoo Finance chart API, cierres diarios ajustados; respaldo automático Stooq cuando Yahoo falla. Sin API key.</li>"
        "<li><b>Fundamentales históricos:</b> SEC EDGAR companyfacts (XBRL) — EPS diluido trimestral con fecha de presentación, ajustado por splits (eventos de Yahoo). Es la base del P/E punto-en-tiempo y del tilt del modelo (validado 8/9 ventanas, +2.02 pp promedio).</li>"
        "<li><b>Valuación viva:</b> Yahoo quoteSummary — P/E actual y forward, estimados de analistas (hoy vs hace 90 días), sector/industria, calendario de resultados. Solo informa el presente; nunca entra a los backtests.</li>"
        "<li><b>Referencias de industria:</b> tabla fija de medianas de P/E por industria/sector (estilo Damodaran) en app/fundamentals/sector_pe.py — editable por diff, no ajustada a backtests.</li>"
        "<li><b>Rendimiento implícito y β:</b> earnings yield = 1 / P/E (forward implícito para acciones; ETF réplica SPY/DIA/QQQ para índices); β = covarianza de retornos diarios contra el S&amp;P 500 / varianza del S&amp;P, ~3 años. Indicadores informativos del resumen — no son insumos del modelo.</li>"
        "<li><b>Descomposición idiosincrático/exógeno:</b> R² del modelo de mercado (β²·var(S&amp;P)/var(activo)) sobre los mismos retornos diarios; cruce SMA20/50 con las ventanas de la estrategia original (SmaCrossoverStrategy); alpha implícito = E/P − β × implícito del S&amp;P. Informativa — no es insumo del modelo.</li>"
        "<li><b>Libro y señales:</b> portfolio_state.json (libro papel) y signals_log.jsonl (registro forward), ambos versionados en el repositorio.</li>"
        "</ul></div>"
    )

    html = f"""<title>Monitor del portafolio</title>
{CSS}
<main>
  <header>
    <p class="eyebrow">Mesa de monitoreo · datos al {fmt_date(as_of)}</p>
    <h1>Monitor del portafolio</h1>
    <div class="hmeta">
      <span class="chip {'up' if state['regime_risk_on'] else 'down'}">régimen {regime_txt}</span>
      <span class="chip">{len(rows)} posiciones</span>
      <span class="chip">efectivo {state['cash_weight']*100:.1f}%</span>
      <span class="chip">libro papel $10,000</span>
      <span class="chip acc">re-selección {fmt_date(state['next_rebalance'])}</span>
    </div>
  </header>

  <section>
    <div class="shead"><h2>Resumen</h2></div>
    <div class="tiles">
      <div class="tile panel"><div class="k">Régimen</div><div class="v">{regime_txt}</div><span class="sub">{regime_sub}</span>{regime_dd}</div>
      <div class="tile panel"><div class="k">Posiciones / efectivo</div><div class="v">{len(rows)} · {state['cash_weight']*100:.1f}%</div><span class="sub">efectivo {money(state['cash_weight'])} de $10,000</span>{book_dd}</div>
      <div class="tile panel"><div class="k">Próxima re-selección</div><div class="v">{fmt_date(state['next_rebalance'])}</div><span class="sub">o antes si una señal saca una posición</span>{reb_dd}</div>
      {key_tile}
    </div>
  </section>

  <section>
    <div class="shead"><h2>Movimientos a ejecutar hoy</h2></div>
    {action_html}
  </section>

  <section>
    <div class="shead"><h2>Posiciones del libro</h2></div>
    <p class="lede">Cada fila se expande: dentro está la aritmética completa de la posición y de dónde sale cada número.</p>
    {pos_section}
  </section>

  <section>
    <div class="shead"><h2>Watchlist — candidatas fuera del libro</h2></div>
    <p class="lede">Las acciones del universo que hoy no están en el libro, con su señal y valuación al día. No hay
    entradas a mitad de trimestre: compiten en la re-selección del {fmt_date(state['next_rebalance'])} por confianza
    ajustada (técnica + tilt de P/E).</p>
    {watch_section}
  </section>

  <section>
    <div class="shead"><h2>Radar de eventos</h2></div>
    <p class="lede">Lo que el modelo está esperando observar y qué decisión dispara cada cosa. Primero los eventos con
    fecha; después los de nivel, que pueden ocurrir cualquier día.</p>
    {events_section}
  </section>

  <section>
    <div class="shead"><h2>Componente idiosincrático vs exógeno</h2></div>
    <p class="lede">Cuánto de cada posición lo mueve el mercado (exógeno: β y régimen, medido como el R² de su
    regresión diaria contra el S&amp;P 500) y cuánto es propio del activo (idiosincrático: su cruce SMA20/50 — la
    estrategia original sobre su propia serie —, su valuación contra su industria y el alpha implícito de su P/E).</p>
    {decomp_section}
  </section>

  <section>
    <div class="shead"><h2>Valuación fundamental (acciones del libro)</h2></div>
    <p class="lede">La línea es el P/E <em>punto-en-tiempo</em> (precio del día entre las utilidades que eran públicas
    ese día, SEC EDGAR, últimos 3 años). Zona verde: barata (&lt;{CHEAP_PE_MAX:.0f}); zona roja: cara
    (&gt;{EXPENSIVE_PE_MIN:.0f}) — las mismas bandas fijas que usa la señal. La línea punteada es la mediana de
    referencia de su industria y el rombo hueco marca el forward P/E implícito del consenso. El drill-down de cada
    tarjeta muestra los 4 trimestres EDGAR exactos que sustentan el múltiplo.</p>
    {valuation_html}
  </section>

  <section>
    <div class="shead"><h2>Fuentes de datos</h2></div>
    {sources_html}
  </section>

  <p class="note"><strong>Cómo leerlo:</strong> "Señal hoy" es la lectura diaria del ensemble — un SELL ≥55% genera
  la orden de salida a efectivo al día siguiente. "Exposición vol." es el ajuste del régimen de volatilidad (100% =
  tamaño completo). El stop-loss marca el precio que fuerza la salida (−15% desde la entrada). El efectivo liberado
  espera hasta la re-selección trimestral — el redespliegue inmediato se probó y se rechazó.
  Libro de papel con precios de cierre; no es asesoría financiera ni garantiza resultados futuros.</p>
</main>
"""
    Path(out_html).write_text(html)
    print(json.dumps({"as_of": as_of, "actions": actions, "positions": len(rows), "watchlist": len(watch), "events": len(events) + len(level_events), "cash_weight": state["cash_weight"], "next_rebalance": state["next_rebalance"]}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
