"""Builds the monthly-returns chart artifact for the last-24-months run
(scripts/run_24m_monthly.py's output)."""

import json

RESULT_PATH = "/home/user/miwebsite/scripts/run_24m_monthly_result.json"
OUT_PATH = "/tmp/claude-0/-home-user/4000c46a-deef-52ab-9f3d-4eef518e131a/scratchpad/sim_24m_monthly_chart.html"

with open(RESULT_PATH, encoding="utf-8") as f:
    data = json.load(f)

monthly = data["monthly"]
best = max(monthly, key=lambda m: m["retorno_mensual_pct"])
worst = min(monthly, key=lambda m: m["retorno_mensual_pct"])
num_up = sum(1 for m in monthly if m["retorno_mensual_pct"] > 0)
num_down = sum(1 for m in monthly if m["retorno_mensual_pct"] < 0)

context = {
    "startDate": data["start_date"],
    "endDate": data["end_date"],
    "portfolio": data["portfolio"],
    "totalReturnPct": data["total_return_pct"],
    "benchmarkReturnPct": data["benchmark_buy_hold_return_pct"],
    "vsBenchmarkPctPoints": data["vs_benchmark_pct_points"],
    "best": best,
    "worst": worst,
    "numUp": num_up,
    "numDown": num_down,
    "monthly": monthly,
}

html = r"""<title>Últimos 24 meses — retorno por mes</title>
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
    background: var(--page); color: var(--text-primary);
    font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
    padding: 24px 16px 48px;
  }
  .wrap { max-width: 980px; margin: 0 auto; }
  h1 { font-size: 1.35rem; margin: 0 0 4px; }
  .subtitle { color: var(--text-secondary); font-size: 0.92rem; margin: 0 0 20px; }
  .stat-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-bottom: 20px; }
  .stat-tile { background: var(--surface-1); border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; }
  .stat-label { font-size: 0.74rem; color: var(--text-secondary); margin-bottom: 4px; }
  .stat-value { font-size: 1.25rem; font-weight: 600; }
  .stat-value.pos { color: var(--good-text); }
  .stat-value.neg { color: var(--series-red); }
  .card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 12px; padding: 16px 16px 10px; margin-bottom: 20px; position: relative; }
  .card h2 { font-size: 0.95rem; margin: 0 0 2px; }
  .card .card-sub { font-size: 0.78rem; color: var(--text-secondary); margin: 0 0 10px; }
  .toggle-row { display: flex; gap: 8px; margin-bottom: 8px; }
  .toggle-row button {
    font: inherit; font-size: 0.78rem; padding: 4px 12px; border-radius: 999px;
    border: 1px solid var(--border); background: transparent; color: var(--text-secondary); cursor: pointer;
  }
  .toggle-row button.active { background: var(--series-blue); border-color: var(--series-blue); color: #fff; }
  .legend { display: flex; gap: 16px; font-size: 0.78rem; color: var(--text-secondary); margin: 4px 0 6px; }
  .legend-item { display: flex; align-items: center; gap: 6px; }
  .legend-swatch { width: 12px; height: 12px; border-radius: 3px; display: inline-block; }
  svg { display: block; width: 100%; height: auto; overflow: visible; }
  .axis-text { fill: var(--text-muted); font-size: 10px; }
  .gridline { stroke: var(--gridline); stroke-width: 1; }
  .baseline { stroke: var(--baseline); stroke-width: 1; }
  .bar-label { fill: var(--text-secondary); font-size: 10px; }
  .tooltip {
    position: absolute; pointer-events: none; opacity: 0; transition: opacity 0.08s;
    background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px;
    padding: 8px 10px; font-size: 0.78rem; box-shadow: 0 4px 16px rgba(0,0,0,0.15);
    white-space: nowrap; z-index: 5;
  }
  .tooltip .t-date { color: var(--text-secondary); margin-bottom: 4px; }
  .tooltip .t-row { display: flex; justify-content: space-between; gap: 14px; }
  .tooltip .t-val { font-weight: 600; }
  table.data-table { width: 100%; border-collapse: collapse; font-size: 0.78rem; font-variant-numeric: tabular-nums; }
  table.data-table th, table.data-table td { text-align: right; padding: 4px 8px; border-bottom: 1px solid var(--gridline); }
  table.data-table th:first-child, table.data-table td:first-child { text-align: left; }
  details summary { cursor: pointer; font-size: 0.85rem; color: var(--text-secondary); }
  .disclaimer { font-size: 0.8rem; color: var(--text-muted); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; background: var(--surface-1); }
  .portfolio-list { display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 20px; padding: 0; list-style: none; }
  .portfolio-list li { background: var(--surface-1); border: 1px solid var(--border); border-radius: 999px; padding: 4px 12px; font-size: 0.8rem; }
</style>

<div class="viz-root">
  <div class="wrap">
    <h1>Modelo actual (long-only) — retorno mes a mes, últimos 24 meses</h1>
    <p class="subtitle" id="subtitle"></p>
    <ul class="portfolio-list" id="portfolioList"></ul>
    <div class="stat-row" id="statRow"></div>

    <div class="card">
      <h2>Retorno por mes</h2>
      <p class="card-sub" id="chartSub"></p>
      <div class="toggle-row">
        <button id="btnAnnual" class="active">Anualizado</button>
        <button id="btnMonthly">Mensual</button>
      </div>
      <div class="legend">
        <span class="legend-item"><span class="legend-swatch" style="background:var(--series-blue)"></span>Mes con ganancia</span>
        <span class="legend-item"><span class="legend-swatch" style="background:var(--series-red)"></span>Mes con pérdida</span>
      </div>
      <svg id="chart" viewBox="0 0 900 260" preserveAspectRatio="none"></svg>
      <div class="tooltip" id="tooltip"></div>
    </div>

    <details class="card">
      <summary>Ver tabla completa (mensual y anualizado)</summary>
      <div style="overflow-x:auto; margin-top:8px;">
        <table class="data-table" id="fullTable">
          <thead><tr><th>Mes</th><th>Retorno mensual</th><th>Equivalente anualizado</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </details>

    <p class="disclaimer">Simulación histórica walk-forward sin lookahead, basada únicamente en
    indicadores técnicos; no es asesoría financiera y no garantiza resultados futuros. El
    anualizado de un solo mes ((1+r)^12−1) exagera tanto lo bueno como lo malo — un mes no es un año.</p>
  </div>
</div>

<script>
const CTX = __CONTEXT__;
const fmtPct = (v) => (v > 0 ? "+" : "") + v.toFixed(2) + "%";

document.getElementById("subtitle").textContent =
  `${CTX.startDate} → ${CTX.endDate} · portafolio elegido al inicio sin ver el futuro · datos reales`;
document.getElementById("chartSub").textContent =
  `${CTX.numUp} meses con ganancia, ${CTX.numDown} con pérdida`;

const portfolioList = document.getElementById("portfolioList");
CTX.portfolio.forEach(p => {
  const li = document.createElement("li");
  li.textContent = `${p.symbol} · ${p.action} ${p.confianza.toFixed(1)}%`;
  portfolioList.appendChild(li);
});

const stats = [
  {label: "Total 24 meses (modelo)", value: fmtPct(CTX.totalReturnPct), cls: CTX.totalReturnPct >= 0 ? "pos" : "neg"},
  {label: "Buy & hold de los mismos símbolos", value: fmtPct(CTX.benchmarkReturnPct), cls: CTX.benchmarkReturnPct >= 0 ? "pos" : "neg"},
  {label: "Modelo vs. no hacer nada", value: fmtPct(CTX.vsBenchmarkPctPoints) + " pp", cls: CTX.vsBenchmarkPctPoints >= 0 ? "pos" : "neg"},
  {label: "Mejor mes", value: `${CTX.best.mes}: ${fmtPct(CTX.best.retorno_mensual_pct)}`, cls: "pos"},
  {label: "Peor mes", value: `${CTX.worst.mes}: ${fmtPct(CTX.worst.retorno_mensual_pct)}`, cls: "neg"},
];
const statRow = document.getElementById("statRow");
stats.forEach(s => {
  const tile = document.createElement("div");
  tile.className = "stat-tile";
  const l = document.createElement("div"); l.className = "stat-label"; l.textContent = s.label;
  const v = document.createElement("div"); v.className = "stat-value" + (s.cls ? " " + s.cls : ""); v.textContent = s.value;
  tile.appendChild(l); tile.appendChild(v);
  statRow.appendChild(tile);
});

const tbody = document.querySelector("#fullTable tbody");
CTX.monthly.forEach(m => {
  const tr = document.createElement("tr");
  [m.mes, fmtPct(m.retorno_mensual_pct), fmtPct(m.equivalente_anualizado_pct)].forEach((c, i) => {
    const td = document.createElement("td");
    td.textContent = c;
    if (i > 0) td.style.color = c.startsWith("+") ? "var(--good-text)" : "var(--series-red)";
    tr.appendChild(td);
  });
  tbody.appendChild(tr);
});

// ---- Chart ----
const W = 900, H = 260;
const margin = {left: 52, right: 8, top: 12, bottom: 24};
const svg = document.getElementById("chart");
const tooltip = document.getElementById("tooltip");
let mode = "annual";

function niceTicks(min, max, count) {
  const span = max - min || 1;
  const step = Math.pow(10, Math.floor(Math.log10(span / count)));
  const norm = span / count / step;
  const mult = norm >= 5 ? 5 : norm >= 2 ? 2 : 1;
  const nice = step * mult;
  const ticks = [];
  for (let t = Math.ceil(min / nice) * nice; t <= max; t += nice) ticks.push(Math.round(t * 100) / 100);
  return ticks;
}

function render() {
  const key = mode === "annual" ? "equivalente_anualizado_pct" : "retorno_mensual_pct";
  const values = CTX.monthly.map(m => m[key]);
  const vMax = Math.max(...values, 0), vMin = Math.min(...values, 0);
  const pad = (vMax - vMin) * 0.12 || 1;
  const yMax = vMax + pad, yMin = vMin - pad;
  const y = v => margin.top + (1 - (v - yMin) / (yMax - yMin)) * (H - margin.top - margin.bottom);
  const zeroY = y(0);

  const n = CTX.monthly.length;
  const slot = (W - margin.left - margin.right) / n;
  const barW = Math.min(24, slot - 2);

  let parts = "";
  niceTicks(yMin, yMax, 4).forEach(t => {
    parts += `<line class="gridline" x1="${margin.left}" x2="${W - margin.right}" y1="${y(t)}" y2="${y(t)}"></line>`;
    parts += `<text class="axis-text" x="${margin.left - 8}" y="${y(t) + 3}" text-anchor="end">${t}%</text>`;
  });
  parts += `<line class="baseline" x1="${margin.left}" x2="${W - margin.right}" y1="${zeroY}" y2="${zeroY}"></line>`;

  CTX.monthly.forEach((m, i) => {
    const v = m[key];
    const x = margin.left + i * slot + (slot - barW) / 2;
    const top = Math.min(y(v), zeroY), h = Math.max(Math.abs(y(v) - zeroY), 1);
    const color = v >= 0 ? "var(--series-blue)" : "var(--series-red)";
    const r = Math.min(4, h);
    // 4px rounded corners at the data end only; square at the zero baseline.
    const path = v >= 0
      ? `M${x},${zeroY} L${x},${top + r} Q${x},${top} ${x + r},${top} L${x + barW - r},${top} Q${x + barW},${top} ${x + barW},${top + r} L${x + barW},${zeroY} Z`
      : `M${x},${zeroY} L${x},${top + h - r} Q${x},${top + h} ${x + r},${top + h} L${x + barW - r},${top + h} Q${x + barW},${top + h} ${x + barW},${top + h - r} L${x + barW},${zeroY} Z`;
    parts += `<path d="${path}" fill="${color}" data-i="${i}"></path>`;
    parts += `<rect x="${margin.left + i * slot}" y="${margin.top}" width="${slot}" height="${H - margin.top - margin.bottom}" fill="transparent" data-i="${i}" class="hit"></rect>`;
    if (i % 3 === 0 || i === n - 1) {
      parts += `<text class="axis-text" x="${x + barW / 2}" y="${H - 6}" text-anchor="middle">${m.mes}</text>`;
    }
  });
  svg.innerHTML = parts;
}

function showTooltip(evt) {
  const i = evt.target.getAttribute("data-i");
  if (i === null) { tooltip.style.opacity = 0; return; }
  const m = CTX.monthly[+i];
  tooltip.innerHTML = "";
  const d = document.createElement("div"); d.className = "t-date"; d.textContent = m.mes; tooltip.appendChild(d);
  [["Mensual", m.retorno_mensual_pct], ["Anualizado", m.equivalente_anualizado_pct]].forEach(([k, v]) => {
    const row = document.createElement("div"); row.className = "t-row";
    const ke = document.createElement("span"); ke.textContent = k;
    const ve = document.createElement("span"); ve.className = "t-val"; ve.textContent = fmtPct(v);
    ve.style.color = v >= 0 ? "var(--good-text)" : "var(--series-red)";
    row.appendChild(ke); row.appendChild(ve); tooltip.appendChild(row);
  });
  const card = svg.closest(".card").getBoundingClientRect();
  let left = evt.clientX - card.left + 14;
  if (left + 170 > card.width) left = evt.clientX - card.left - 184;
  tooltip.style.left = left + "px";
  tooltip.style.top = (evt.clientY - card.top - 10) + "px";
  tooltip.style.opacity = 1;
}

svg.addEventListener("pointermove", showTooltip);
svg.addEventListener("pointerleave", () => { tooltip.style.opacity = 0; });

const btnA = document.getElementById("btnAnnual"), btnM = document.getElementById("btnMonthly");
btnA.addEventListener("click", () => { mode = "annual"; btnA.classList.add("active"); btnM.classList.remove("active"); render(); });
btnM.addEventListener("click", () => { mode = "monthly"; btnM.classList.add("active"); btnA.classList.remove("active"); render(); });
render();
</script>
"""

html = html.replace("__CONTEXT__", json.dumps(context, ensure_ascii=False))
with open(OUT_PATH, "w", encoding="utf-8") as f:
    f.write(html)
print("wrote", OUT_PATH, len(html), "bytes")
