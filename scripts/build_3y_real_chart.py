"""Builds the daily-P&L / equity-curve HTML artifact for the 3-year real-data
portfolio simulation (scripts/run_3y_real_sim.py's output)."""

import json
import os

RESULT_PATH = "/home/user/miwebsite/scripts/sim_3y_real_result.json"
OLD_RESULT_PATH = "/home/user/miwebsite/scripts/sim_3y_real_result_OLD_confidence_ranking.json"
OUT_PATH = "/tmp/claude-0/-home-user/4000c46a-deef-52ab-9f3d-4eef518e131a/scratchpad/sim_3y_real_chart.html"

with open(RESULT_PATH, encoding="utf-8") as f:
    report = json.load(f)

old_report = None
if os.path.exists(OLD_RESULT_PATH):
    with open(OLD_RESULT_PATH, encoding="utf-8") as f:
        old_report = json.load(f)

curve = report["portfolio_equity_curve"]
dates = [c["date"] for c in curve]
equity = [c["equity"] for c in curve]

daily_pnl = [0.0] + [round(equity[i] - equity[i - 1], 2) for i in range(1, len(equity))]

max_drawdown_pct = 0.0
peak = equity[0]
for v in equity:
    if v > peak:
        peak = v
    dd = (v / peak - 1) * 100
    if dd < max_drawdown_pct:
        max_drawdown_pct = dd

best_day = max(range(len(daily_pnl)), key=lambda i: daily_pnl[i])
worst_day = min(range(len(daily_pnl)), key=lambda i: daily_pnl[i])
num_up_days = sum(1 for p in daily_pnl[1:] if p > 0)
num_down_days = sum(1 for p in daily_pnl[1:] if p < 0)

payload = {
    "dates": dates,
    "equity": equity,
    "dailyPnl": daily_pnl,
}

context = {
    "startDate": report["start_date"],
    "endDate": report["end_date"],
    "numTradingDays": report["num_trading_days"],
    "initialCapital": report["initial_capital"],
    "finalEquity": report["final_equity"],
    "totalPnlAmount": report["total_pnl_amount"],
    "totalReturnPct": report["total_return_pct"],
    "maxDrawdownPct": round(max_drawdown_pct, 2),
    "bestDay": {"date": dates[best_day], "pnl": daily_pnl[best_day]},
    "worstDay": {"date": dates[worst_day], "pnl": daily_pnl[worst_day]},
    "numUpDays": num_up_days,
    "numDownDays": num_down_days,
    "portfolio": report["portfolio"],
    "perSymbol": [
        {
            "symbol": p["symbol"],
            "finalEquity": p["final_equity"],
            "pnlAmount": p["pnl_amount"],
            "numTrades": p["metrics"]["num_trades"],
            "winRatePct": p["metrics"]["win_rate_pct"],
        }
        for p in report["per_symbol"]
    ],
    "hindsight": report["hindsight_summary"],
    "disclaimer": report["disclaimer"],
    "oldComparison": None
    if old_report is None
    else {
        "finalEquity": old_report["final_equity"],
        "totalPnlAmount": old_report["total_pnl_amount"],
        "totalReturnPct": old_report["total_return_pct"],
        "portfolioSymbols": [p["symbol"] for p in old_report["portfolio"]],
    },
}

html = r"""<title>Simulación 3 años — datos reales</title>
<style>
  .viz-root {
    color-scheme: light;
    --surface-1:      #fcfcfb;
    --page:           #f9f9f7;
    --text-primary:   #0b0b0b;
    --text-secondary: #52514e;
    --text-muted:     #898781;
    --gridline:       #e1e0d9;
    --baseline:       #c3c2b7;
    --border:         rgba(11,11,11,0.10);
    --series-blue:    #2a78d6;
    --series-red:     #e34948;
    --good-text:      #006300;
  }
  @media (prefers-color-scheme: dark) {
    :root:where(:not([data-theme="light"])) .viz-root {
      color-scheme: dark;
      --surface-1:      #1a1a19;
      --page:           #0d0d0d;
      --text-primary:   #ffffff;
      --text-secondary: #c3c2b7;
      --text-muted:     #898781;
      --gridline:       #2c2c2a;
      --baseline:       #383835;
      --border:         rgba(255,255,255,0.10);
      --series-blue:    #3987e5;
      --series-red:     #e66767;
      --good-text:      #0ca30c;
    }
  }
  :root[data-theme="dark"] .viz-root {
    color-scheme: dark;
    --surface-1:      #1a1a19;
    --page:           #0d0d0d;
    --text-primary:   #ffffff;
    --text-secondary: #c3c2b7;
    --text-muted:     #898781;
    --gridline:       #2c2c2a;
    --baseline:       #383835;
    --border:         rgba(255,255,255,0.10);
    --series-blue:    #3987e5;
    --series-red:     #e66767;
    --good-text:      #0ca30c;
  }

  * { box-sizing: border-box; }
  body { margin: 0; }
  .viz-root {
    background: var(--page);
    color: var(--text-primary);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    padding: 24px 16px 48px;
  }
  .wrap { max-width: 980px; margin: 0 auto; }
  h1 { font-size: 1.35rem; margin: 0 0 4px; }
  .subtitle { color: var(--text-secondary); font-size: 0.92rem; margin: 0 0 20px; }
  .disclaimer {
    font-size: 0.8rem; color: var(--text-muted); border: 1px solid var(--border);
    border-radius: 8px; padding: 10px 14px; margin-bottom: 24px; background: var(--surface-1);
  }

  .stat-row {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
    gap: 10px; margin-bottom: 20px;
  }
  .stat-tile {
    background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px;
    padding: 12px 14px;
  }
  .stat-label { font-size: 0.74rem; color: var(--text-secondary); margin-bottom: 4px; }
  .stat-value { font-size: 1.25rem; font-weight: 600; }
  .stat-value.pos { color: var(--good-text); }
  .stat-value.neg { color: var(--series-red); }

  .card {
    background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px;
    padding: 16px 16px 8px; margin-bottom: 20px; position: relative;
  }
  .card h2 { font-size: 0.95rem; margin: 0 0 2px; }
  .card .card-sub { font-size: 0.78rem; color: var(--text-secondary); margin: 0 0 8px; }

  .legend { display: flex; gap: 16px; font-size: 0.78rem; color: var(--text-secondary); margin: 4px 0 6px; }
  .legend-item { display: flex; align-items: center; gap: 6px; }
  .legend-swatch { width: 14px; height: 2px; border-radius: 1px; display: inline-block; }

  svg { display: block; width: 100%; height: auto; overflow: visible; }
  .axis-text { fill: var(--text-muted); font-size: 10px; }
  .gridline { stroke: var(--gridline); stroke-width: 1; }
  .baseline { stroke: var(--baseline); stroke-width: 1; }

  .crosshair-line { stroke: var(--text-muted); stroke-width: 1; pointer-events: none; opacity: 0; }
  .hover-dot { r: 4; stroke: var(--surface-1); stroke-width: 2; pointer-events: none; opacity: 0; }

  .tooltip {
    position: absolute; pointer-events: none; opacity: 0; transition: opacity 0.08s;
    background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px;
    padding: 8px 10px; font-size: 0.78rem; box-shadow: 0 4px 16px rgba(0,0,0,0.15);
    white-space: nowrap; z-index: 5;
  }
  .tooltip .t-date { color: var(--text-secondary); margin-bottom: 4px; }
  .tooltip .t-row { display: flex; justify-content: space-between; gap: 14px; }
  .tooltip .t-row .t-key { color: var(--text-secondary); display: flex; align-items: center; gap: 6px; }
  .tooltip .t-row .t-val { font-weight: 600; }
  .tooltip .t-key-line { width: 10px; height: 2px; display: inline-block; }

  table.data-table {
    width: 100%; border-collapse: collapse; font-size: 0.78rem;
    font-variant-numeric: tabular-nums;
  }
  table.data-table th, table.data-table td {
    text-align: right; padding: 4px 8px; border-bottom: 1px solid var(--gridline);
  }
  table.data-table th:first-child, table.data-table td:first-child { text-align: left; }
  .table-scroll { max-height: 360px; overflow-y: auto; border: 1px solid var(--border); border-radius: 8px; margin-top: 8px; }
  details summary { cursor: pointer; font-size: 0.85rem; color: var(--text-secondary); margin-top: 4px; }

  .portfolio-list { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0 0; padding: 0; list-style: none; }
  .portfolio-list li {
    background: var(--surface-1); border: 1px solid var(--border); border-radius: 999px;
    padding: 4px 12px; font-size: 0.8rem; display: flex; gap: 6px; align-items: center;
  }
  .tag-buy { color: var(--good-text); font-weight: 600; }
  .tag-sell { color: var(--series-red); font-weight: 600; }

  .sym-table td, .sym-table th { text-align: right; }
  .sym-table td:first-child, .sym-table th:first-child { text-align: left; }
</style>

<div class="viz-root">
  <div class="wrap">
    <h1>Simulador de portafolio — 3 años con datos reales</h1>
    <p class="subtitle" id="subtitle"></p>

    <div class="card" id="comparisonCard" style="display:none;">
      <h2>Antes / después: selección ajustada por riesgo (Sharpe/drawdown)</h2>
      <p class="card-sub" id="comparisonSub"></p>
    </div>

    <div class="stat-row" id="statRow"></div>

    <div class="card">
      <h2>Curva de equity acumulada</h2>
      <p class="card-sub">Capital total del portafolio, día a día</p>
      <svg id="equityChart" viewBox="0 0 900 220" preserveAspectRatio="none"></svg>
    </div>

    <div class="card">
      <h2>Ganancia / pérdida diaria</h2>
      <p class="card-sub">Cambio del capital total respecto al día anterior</p>
      <div class="legend">
        <span class="legend-item"><span class="legend-swatch" style="background:var(--series-blue)"></span>Día con ganancia</span>
        <span class="legend-item"><span class="legend-swatch" style="background:var(--series-red)"></span>Día con pérdida</span>
      </div>
      <svg id="pnlChart" viewBox="0 0 900 180" preserveAspectRatio="none"></svg>
      <div class="tooltip" id="tooltip"></div>
    </div>

    <div class="card">
      <h2>Portafolio seleccionado (antes del inicio, sin ver datos futuros)</h2>
      <ul class="portfolio-list" id="portfolioList"></ul>
      <div style="overflow-x:auto; margin-top: 12px;">
        <table class="data-table sym-table" id="symTable">
          <thead>
            <tr><th>Símbolo</th><th>Capital final</th><th>P&amp;L</th><th># operaciones</th><th>% acierto</th></tr>
          </thead>
          <tbody></tbody>
        </table>
      </div>
    </div>

    <div class="card">
      <h2>Aprendizaje de posiciones pasadas (hindsight)</h2>
      <p class="card-sub" id="hindsightSub"></p>
    </div>

    <details class="card">
      <summary>Ver tabla completa (día, ganancia/pérdida, capital acumulado)</summary>
      <div class="table-scroll">
        <table class="data-table" id="fullTable">
          <thead><tr><th>Fecha</th><th>Ganancia/pérdida del día</th><th>Capital acumulado</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </details>

    <p class="disclaimer" id="disclaimer"></p>
  </div>
</div>

<script>
const DATA = __PAYLOAD__;
const CTX = __CONTEXT__;

const fmtMoney = (v) => (v < 0 ? "-$" : "$") + Math.abs(v).toLocaleString("es-MX", {minimumFractionDigits: 2, maximumFractionDigits: 2});
const fmtPct = (v) => (v > 0 ? "+" : "") + v.toFixed(2) + "%";

document.getElementById("subtitle").textContent =
  `${CTX.startDate} → ${CTX.endDate} · ${CTX.numTradingDays} días de mercado · datos reales (Yahoo Finance)`;

document.getElementById("disclaimer").textContent = CTX.disclaimer;

if (CTX.oldComparison) {
  const old = CTX.oldComparison;
  document.getElementById("comparisonCard").style.display = "";
  const sub = document.getElementById("comparisonSub");
  sub.innerHTML = "";
  const line1 = document.createElement("div");
  line1.innerHTML =
    `Antes (ranking por pura confianza del ensemble): portafolio <strong>${old.portfolioSymbols.join(", ")}</strong> → ` +
    `<span style="color:var(--series-red)">${fmtMoney(old.totalPnlAmount)} (${fmtPct(old.totalReturnPct)})</span>`;
  const line2 = document.createElement("div");
  line2.style.marginTop = "4px";
  line2.innerHTML =
    `Ahora (ranking ajustado por Sharpe/drawdown histórico): portafolio <strong>${CTX.portfolio.map(p => p.symbol).join(", ")}</strong> → ` +
    `<span style="color:${CTX.totalPnlAmount >= 0 ? 'var(--good-text)' : 'var(--series-red)'}">${fmtMoney(CTX.totalPnlAmount)} (${fmtPct(CTX.totalReturnPct)})</span>`;
  sub.appendChild(line1);
  sub.appendChild(line2);
}

const stats = [
  {label: "Capital inicial", value: fmtMoney(CTX.initialCapital)},
  {label: "Capital final", value: fmtMoney(CTX.finalEquity), cls: CTX.finalEquity >= CTX.initialCapital ? "pos" : "neg"},
  {label: "Ganancia / pérdida total", value: fmtMoney(CTX.totalPnlAmount) + " (" + fmtPct(CTX.totalReturnPct) + ")", cls: CTX.totalPnlAmount >= 0 ? "pos" : "neg"},
  {label: "Drawdown máximo", value: CTX.maxDrawdownPct.toFixed(2) + "%", cls: "neg"},
  {label: "Días con ganancia / pérdida", value: CTX.numUpDays + " / " + CTX.numDownDays},
  {label: "Mejor día", value: fmtMoney(CTX.bestDay.pnl), cls: "pos"},
  {label: "Peor día", value: fmtMoney(CTX.worstDay.pnl), cls: "neg"},
];
const statRow = document.getElementById("statRow");
stats.forEach(s => {
  const tile = document.createElement("div");
  tile.className = "stat-tile";
  const label = document.createElement("div");
  label.className = "stat-label";
  label.textContent = s.label;
  const value = document.createElement("div");
  value.className = "stat-value" + (s.cls ? " " + s.cls : "");
  value.textContent = s.value;
  tile.appendChild(label);
  tile.appendChild(value);
  statRow.appendChild(tile);
});

const portfolioList = document.getElementById("portfolioList");
CTX.portfolio.forEach(p => {
  const li = document.createElement("li");
  const sym = document.createElement("span");
  sym.textContent = p.symbol;
  const action = document.createElement("span");
  action.className = p.action_at_selection === "BUY" ? "tag-buy" : "tag-sell";
  action.textContent = p.action_at_selection + " " + p.confidence_pct_at_selection.toFixed(1) + "%";
  li.appendChild(sym);
  li.appendChild(action);
  portfolioList.appendChild(li);
});

const symTbody = document.querySelector("#symTable tbody");
CTX.perSymbol.forEach(p => {
  const tr = document.createElement("tr");
  const cells = [p.symbol, fmtMoney(p.finalEquity), fmtMoney(p.pnlAmount), String(p.numTrades), p.winRatePct.toFixed(1) + "%"];
  cells.forEach((c, i) => {
    const td = document.createElement("td");
    td.textContent = c;
    if (i === 2) td.style.color = p.pnlAmount >= 0 ? "var(--good-text)" : "var(--series-red)";
    tr.appendChild(td);
  });
  symTbody.appendChild(tr);
});

const h = CTX.hindsight;
document.getElementById("hindsightSub").textContent =
  `De ${h.num_trades} operaciones cerradas, ${h.num_optimal} (${h.pct_optimal}%) fueron la mejor opción posible en retrospectiva (largo/corto/plano). ` +
  `Regret promedio: ${h.avg_regret_pct}%. Dinero dejado sobre la mesa por no haber tomado la mejor posición: ${fmtMoney(h.total_missed_pnl_amount)}.`;

const fullTbody = document.querySelector("#fullTable tbody");
const frag = document.createDocumentFragment();
DATA.dates.forEach((d, i) => {
  const tr = document.createElement("tr");
  const tdDate = document.createElement("td"); tdDate.textContent = d;
  const tdPnl = document.createElement("td"); tdPnl.textContent = fmtMoney(DATA.dailyPnl[i]);
  tdPnl.style.color = DATA.dailyPnl[i] >= 0 ? "var(--good-text)" : "var(--series-red)";
  const tdEq = document.createElement("td"); tdEq.textContent = fmtMoney(DATA.equity[i]);
  tr.appendChild(tdDate); tr.appendChild(tdPnl); tr.appendChild(tdEq);
  frag.appendChild(tr);
});
fullTbody.appendChild(frag);

// ---- Charts ----
const margin = {left: 56, right: 12, top: 10, bottom: 20};
const eqW = 900, eqH = 220;
const pnlW = 900, pnlH = 180;
const n = DATA.dates.length;

function xScale(i, width) {
  return margin.left + (i / (n - 1)) * (width - margin.left - margin.right);
}

function niceTicks(min, max, count) {
  const span = max - min || 1;
  const step = Math.pow(10, Math.floor(Math.log10(span / count)));
  const norm = span / count / step;
  const mult = norm >= 5 ? 5 : norm >= 2 ? 2 : 1;
  const niceStep = step * mult;
  const ticks = [];
  let t = Math.ceil(min / niceStep) * niceStep;
  for (; t <= max; t += niceStep) ticks.push(Math.round(t * 100) / 100);
  return ticks;
}

function buildEquityChart() {
  const svg = document.getElementById("equityChart");
  const eqMin = Math.min(...DATA.equity, CTX.initialCapital);
  const eqMax = Math.max(...DATA.equity, CTX.initialCapital);
  const pad = (eqMax - eqMin) * 0.08 || 1;
  const yMin = eqMin - pad, yMax = eqMax + pad;
  const yScale = (v) => margin.top + (1 - (v - yMin) / (yMax - yMin)) * (eqH - margin.top - margin.bottom);

  const ticks = niceTicks(yMin, yMax, 4);
  let gridSvg = "";
  ticks.forEach(t => {
    const y = yScale(t);
    gridSvg += `<line class="gridline" x1="${margin.left}" x2="${eqW - margin.right}" y1="${y}" y2="${y}"></line>`;
    gridSvg += `<text class="axis-text" x="${margin.left - 8}" y="${y + 3}" text-anchor="end">$${t.toLocaleString("en-US")}</text>`;
  });

  let path = "";
  for (let i = 0; i < n; i++) {
    const x = xScale(i, eqW), y = yScale(DATA.equity[i]);
    path += (i === 0 ? "M" : "L") + x.toFixed(2) + "," + y.toFixed(2) + " ";
  }
  const baseY = yScale(yMin);
  const areaPath = path + `L${xScale(n - 1, eqW).toFixed(2)},${baseY} L${xScale(0, eqW).toFixed(2)},${baseY} Z`;

  const xTickIdx = [0, Math.floor((n - 1) * 0.25), Math.floor((n - 1) * 0.5), Math.floor((n - 1) * 0.75), n - 1];
  let xAxisSvg = "";
  xTickIdx.forEach(i => {
    const x = xScale(i, eqW);
    xAxisSvg += `<text class="axis-text" x="${x}" y="${eqH - 4}" text-anchor="middle">${DATA.dates[i]}</text>`;
  });

  svg.innerHTML = gridSvg + xAxisSvg +
    `<path d="${areaPath}" fill="var(--series-blue)" opacity="0.10"></path>` +
    `<path d="${path}" fill="none" stroke="var(--series-blue)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"></path>` +
    `<line id="eqCrosshair" class="crosshair-line" x1="0" x2="0" y1="${margin.top}" y2="${eqH - margin.bottom}"></line>` +
    `<circle id="eqDot" class="hover-dot" fill="var(--series-blue)"></circle>`;

  return {yScale};
}

function buildPnlChart() {
  const svg = document.getElementById("pnlChart");
  const pnlMax = Math.max(...DATA.dailyPnl.map(Math.abs), 1);
  const yMin = -pnlMax * 1.1, yMax = pnlMax * 1.1;
  const yScale = (v) => margin.top + (1 - (v - yMin) / (yMax - yMin)) * (pnlH - margin.top - margin.bottom);
  const zeroY = yScale(0);

  const ticks = niceTicks(yMin, yMax, 4);
  let gridSvg = "";
  ticks.forEach(t => {
    const y = yScale(t);
    gridSvg += `<line class="gridline" x1="${margin.left}" x2="${pnlW - margin.right}" y1="${y}" y2="${y}"></line>`;
    gridSvg += `<text class="axis-text" x="${margin.left - 8}" y="${y + 3}" text-anchor="end">$${t.toLocaleString("en-US")}</text>`;
  });

  let posPath = `M${xScale(0, pnlW).toFixed(2)},${zeroY.toFixed(2)} `;
  let negPath = `M${xScale(0, pnlW).toFixed(2)},${zeroY.toFixed(2)} `;
  for (let i = 0; i < n; i++) {
    const x = xScale(i, pnlW);
    const v = DATA.dailyPnl[i];
    const y = yScale(v);
    posPath += `L${x.toFixed(2)},${(v >= 0 ? y : zeroY).toFixed(2)} `;
    negPath += `L${x.toFixed(2)},${(v <= 0 ? y : zeroY).toFixed(2)} `;
  }
  const lastX = xScale(n - 1, pnlW).toFixed(2);
  posPath += `L${lastX},${zeroY.toFixed(2)} Z`;
  negPath += `L${lastX},${zeroY.toFixed(2)} Z`;

  const xTickIdx = [0, Math.floor((n - 1) * 0.25), Math.floor((n - 1) * 0.5), Math.floor((n - 1) * 0.75), n - 1];
  let xAxisSvg = "";
  xTickIdx.forEach(i => {
    const x = xScale(i, pnlW);
    xAxisSvg += `<text class="axis-text" x="${x}" y="${pnlH - 4}" text-anchor="middle">${DATA.dates[i]}</text>`;
  });

  svg.innerHTML = gridSvg + xAxisSvg +
    `<line class="baseline" x1="${margin.left}" x2="${pnlW - margin.right}" y1="${zeroY}" y2="${zeroY}"></line>` +
    `<path d="${posPath}" fill="var(--series-blue)" opacity="0.55"></path>` +
    `<path d="${negPath}" fill="var(--series-red)" opacity="0.55"></path>` +
    `<line id="pnlCrosshair" class="crosshair-line" x1="0" x2="0" y1="${margin.top}" y2="${pnlH - margin.bottom}"></line>` +
    `<circle id="pnlDot" class="hover-dot"></circle>`;

  return {yScale, zeroY};
}

const eqScales = buildEquityChart();
const pnlScales = buildPnlChart();

// Shared crosshair + tooltip across both charts, keyed on the bottom (pnl) chart's pointer position.
const pnlSvg = document.getElementById("pnlChart");
const eqCrosshair = document.getElementById("eqCrosshair");
const pnlCrosshair = document.getElementById("pnlCrosshair");
const eqDot = document.getElementById("eqDot");
const pnlDot = document.getElementById("pnlDot");
const tooltip = document.getElementById("tooltip");

function nearestIndex(px, width) {
  const rel = (px - margin.left) / (width - margin.left - margin.right);
  return Math.min(n - 1, Math.max(0, Math.round(rel * (n - 1))));
}

function onMove(evt) {
  const rect = pnlSvg.getBoundingClientRect();
  const px = ((evt.clientX - rect.left) / rect.width) * pnlW;
  const i = nearestIndex(px, pnlW);
  const x = xScale(i, pnlW);

  eqCrosshair.setAttribute("x1", x); eqCrosshair.setAttribute("x2", x); eqCrosshair.style.opacity = 1;
  pnlCrosshair.setAttribute("x1", x); pnlCrosshair.setAttribute("x2", x); pnlCrosshair.style.opacity = 1;

  const eqY = eqScales.yScale(DATA.equity[i]);
  eqDot.setAttribute("cx", x); eqDot.setAttribute("cy", eqY); eqDot.style.opacity = 1;

  const pnlVal = DATA.dailyPnl[i];
  const pnlY = pnlScales.yScale(pnlVal);
  pnlDot.setAttribute("cx", x); pnlDot.setAttribute("cy", pnlY); pnlDot.style.opacity = 1;
  pnlDot.setAttribute("fill", pnlVal >= 0 ? "var(--series-blue)" : "var(--series-red)");

  tooltip.innerHTML = "";
  const dateEl = document.createElement("div");
  dateEl.className = "t-date";
  dateEl.textContent = DATA.dates[i];
  tooltip.appendChild(dateEl);

  const rowsData = [
    {key: "Ganancia/pérdida del día", val: fmtMoney(pnlVal), color: pnlVal >= 0 ? "var(--series-blue)" : "var(--series-red)"},
    {key: "Capital acumulado", val: fmtMoney(DATA.equity[i]), color: "var(--series-blue)"},
  ];
  rowsData.forEach(r => {
    const row = document.createElement("div");
    row.className = "t-row";
    const keyEl = document.createElement("span");
    keyEl.className = "t-key";
    const lineEl = document.createElement("span");
    lineEl.className = "t-key-line";
    lineEl.style.background = r.color;
    keyEl.appendChild(lineEl);
    keyEl.appendChild(document.createTextNode(r.key));
    const valEl = document.createElement("span");
    valEl.className = "t-val";
    valEl.textContent = r.val;
    row.appendChild(keyEl);
    row.appendChild(valEl);
    tooltip.appendChild(row);
  });

  const cardRect = pnlSvg.closest(".card").getBoundingClientRect();
  let left = evt.clientX - cardRect.left + 14;
  const top = evt.clientY - cardRect.top - 10;
  if (left + 180 > cardRect.width) left = evt.clientX - cardRect.left - 194;
  tooltip.style.left = left + "px";
  tooltip.style.top = top + "px";
  tooltip.style.opacity = 1;
}

function onLeave() {
  eqCrosshair.style.opacity = 0;
  pnlCrosshair.style.opacity = 0;
  eqDot.style.opacity = 0;
  pnlDot.style.opacity = 0;
  tooltip.style.opacity = 0;
}

pnlSvg.addEventListener("pointermove", onMove);
pnlSvg.addEventListener("pointerleave", onLeave);
document.getElementById("equityChart").addEventListener("pointermove", onMove);
document.getElementById("equityChart").addEventListener("pointerleave", onLeave);
</script>
"""

html = html.replace("__PAYLOAD__", json.dumps(payload)).replace("__CONTEXT__", json.dumps(context))

with open(OUT_PATH, "w", encoding="utf-8") as f:
    f.write(html)

print("wrote", OUT_PATH, len(html), "bytes")
print("context:", json.dumps(context, indent=2, ensure_ascii=False)[:2000])
