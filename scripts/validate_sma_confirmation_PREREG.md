# Hipótesis 7 — Confirmación para BUYs respaldados por sma_crossover

**Pre-registro escrito y commiteado ANTES de correr la validación.**
Fecha: 2026-11-12. Regla inmutable: nada de lo que sigue se ajusta después
de ver los números.

## Motivación (evidencia fuera de muestra, previa e independiente)

Log de seguimiento hacia adelante (`signals_log.jsonl`, corte 2026-11-09,
n=394, 125 señales con estrategia atribuida, horizonte 10 días):

| Rebanada | Aciertos | Retorno fwd medio |
|---|---|---|
| sma_crossover **BUY** | **4/35 (11%)** | **−2.97%** |
| sma_crossover SELL | 48/61 (79%) | −3.04% (acierta) |
| trend_confirmation BUY | 11/12 (92%) | +1.58% |

Los BUY respaldados por sma_crossover son la rebanada débil clara; los SELL
de la misma estrategia funcionan. La hipótesis nació de este patrón (3 cortes
semanales consecutivos), no de la autopsia de una ventana del backtest.

## Mecanismo exacto (brazo B)

Toggle `sma_buy_confirmation` (default False) en `_select_portfolio` /
`_run_simulation`. Solo en la selección de cartera (frontera inicial y cada
rebalanceo); el walk-forward diario, stops, sizing y todo lo demás quedan
intactos:

- Un candidato con `overall_action == "BUY"` cuyo
  `best_historical_strategy.strategy` empieza con `"sma_crossover"` se
  **excluye** de la selección SALVO que la estrategia `trend_confirmation`
  esté alcista para ese símbolo en esa misma frontera
  (`per_strategy` → señal en `{"BUY", "HOLD_LONG"}`, es decir, posición larga).
- Todo lo demás (otros BUYs, todos los SELLs del escáner, HOLDs) no cambia.
- Sin lookahead: usa la misma ventana estrictamente anterior al primer día
  simulado que ya usa `_select_portfolio`.

## Brazos y datos

- **A (default actual):** long-only, selección ajustada por riesgo, tope 2
  por clase, risk parity, stop 15%, confianza mínima 55,
  `risk_regime_sizing`, rebalanceo 3m, `equity_regime_tilt`,
  `fundamental_pe_tilt`. Números por ventana leídos del comiteado
  `scripts/validate_pe_tilt_result.json` (brazo `pe_tilt_return_pct`), sin
  re-correr.
- **B:** A + `sma_buy_confirmation=True`.
- Ventanas: las mismas 9 (2004-07-30 … 2023-07-30, warmup 2a, sim 3a),
  mismo universo (`EXAMPLE_SYMBOLS`), mismo `get_ohlcv`.

## Regla de decisión (fijada ahora)

**ADOPTAR** `sma_buy_confirmation` como default solo si se cumplen LAS CUATRO:

1. **Actúa de verdad:** al menos 2 de las 9 ventanas cambian de retorno
   (|delta| > 0.01 pp). Si cambia menos, RECHAZAR por falta de evidencia en
   backtest (el log hacia adelante sigue acumulando evidencia real).
2. **Gana donde actúa:** entre las ventanas que cambian, las que mejoran son
   estrictamente más que las que empeoran.
3. **Media positiva:** el delta medio de retorno sobre las 9 ventanas es > 0.
4. **Guardia de crisis:** ninguna de las dos ventanas de crisis (2007-2010,
   2017-2020) empeora más de 10 pp — la protección en crisis es la razón de
   ser del modelo.

Si falla cualquiera: **RECHAZAR** y mantener el default (marcador pasa a
5 adoptadas / 7 rechazadas). Drawdown y vs-S&P se reportan por honestidad
pero no son parte del listón.
