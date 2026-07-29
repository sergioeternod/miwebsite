# Trading Signals App

App de trading para proyecciones e inversiones multi-instrumento (acciones,
cripto, divisas, commodities, índices): backtesting de estrategias técnicas y
recomendaciones de compra/venta basadas en indicadores técnicos e
información histórica de mercado.

> ⚠️ **No es asesoría financiera.** Las recomendaciones se generan a partir de
> indicadores técnicos y backtests históricos. El desempeño pasado no
> garantiza resultados futuros. Verifica siempre con tu propio criterio antes
> de operar con dinero real.

## Qué incluye esta primera fase (MVP)

- **Datos multi-instrumento**: una sola fuente (Yahoo Finance vía `yfinance`)
  cubre acciones, cripto, divisas, commodities e índices con el mismo formato
  OHLCV, usando el símbolo de cada instrumento (`AAPL`, `BTC-USD`,
  `EURUSD=X`, `GC=F`, `^GSPC`, etc.).
- **Indicadores técnicos**: SMA, EMA, RSI, MACD, Bandas de Bollinger, ATR
  (`app/indicators/technical.py`).
- **Estrategias, long y short** (con flag `allow_short` para restringir a
  solo-largo cuando el instrumento/cuenta no permite shortear, ej. cripto
  spot sin margen):
  - `sma_crossover` — seguimiento de tendencia (cruce de medias móviles)
  - `macd_crossover` — seguimiento de tendencia (cruce de MACD/señal)
  - `rsi_reversion` — reversión a la media (rebote/techo confirmado en RSI)
  - `bollinger_breakout` — ruptura de momentum (banda superior/inferior)
  - `trend_confirmation` — momentum filtrado por tendencia: solo toma la
    señal de MACD cuando coincide con la tendencia de una SMA larga (menos
    operaciones, buscando mayor ganancia promedio por operación al evitar
    señales en contra de la tendencia)
- **Motor de backtesting** long/short con métricas por estrategia e
  instrumento: retorno total, CAGR, máximo drawdown, Sharpe ratio, win rate,
  **ganancia promedio por transacción**, mejor/peor operación, profit factor.
  `compare_strategies` rankea las estrategias por ganancia promedio por
  transacción para identificar cuál tiene mayor capacidad de ganancia en un
  instrumento dado.
- **Simulador** (`app/simulate.py`): corre una estrategia (o todas) sobre
  datos históricos reales o sobre un escenario sintético multi-régimen
  (`app/data/synthetic.py`, con tramos alcistas/correctivos/laterales/bajistas)
  y devuelve un reporte completo (métricas, bitácora de operaciones, curva de
  capital, serie de precios) — útil para validar el motor sin depender de
  acceso a internet. Acepta `start_date`/`end_date` para simular sobre un
  rango de fechas exacto en vez de un periodo relativo.
- **Pantalla web del simulador** (`app/static/index.html`, servida en `/` por
  la API): formulario para elegir símbolo (o escenario sintético), rango de
  fechas, estrategia y shorts, con gráfico de precio + señales, curva de
  capital comparada contra buy&hold, tabla de métricas y bitácora de
  operaciones — todo interactivo (hover con tooltip, selector de estrategia).
- **Motor de recomendaciones**: ejecuta todas las estrategias sobre los datos
  más recientes y combina sus señales (BUY/SELL_SHORT/HOLD) ponderadas por el
  desempeño histórico de cada estrategia en ese instrumento específico,
  devolviendo una recomendación con nivel de confianza y el razonamiento
  técnico detrás.
- **Validación: expectativa vs realidad** (`app/validation/`) — tres análisis
  que comparan lo que una estrategia/recomendación "esperaba" contra lo que
  realmente pasó después:
  1. **Fuera de muestra** (`out_of_sample.py`): divide el histórico en dos
     periodos consecutivos; el desempeño del primero es la "expectativa", el
     del segundo la "realidad" — ¿la estrategia siguió funcionando después?
  2. **Precisión direccional** (`trade_accuracy.py`): por cada operación,
     ¿la dirección esperada (compra=sube, corto=baja) coincidió con lo que
     pasó? Hit rate por estrategia y por dirección (long/short).
  3. **Precisión del motor de recomendaciones** (`recommendation_accuracy.py`):
     recalcula la recomendación ensemble en muchas fechas históricas usando
     solo datos disponibles hasta ese momento (sin lookahead) y compara contra
     el retorno real N barras después — valida qué tan confiable es la
     recomendación BUY/SELL/HOLD en la práctica.
- **API REST (FastAPI)** y **CLI** para correr backtests, simulaciones,
  recomendaciones y validaciones.
- Suite de tests (`pytest`, 69 casos) sobre datos sintéticos, sin depender de
  red — incluye cobertura de posiciones largas y cortas, rangos de fecha, y
  las tres validaciones de expectativa vs realidad.

## Comparación de las 5 estrategias

Sobre el mismo escenario histórico sintético (alza → corrección → lateral →
caída fuerte → recuperación), rankeadas por ganancia promedio por
transacción:

| Estrategia | Retorno total | Ganancia/operación | Win rate | Profit factor | Máx. drawdown | Operaciones |
|---|---|---|---|---|---|---|
| Cruce de SMA | +18.82% | **+5.89%** | 60.0% | 2.18 | -23.06% | 5 |
| Ruptura Bollinger | +62.79% | +5.76% | 60.0% | 6.20 | -13.92% | 10 |
| Confirmación de tendencia | +30.32% | +3.58% | 40.0% | 2.50 | -18.64% | 10 |
| Cruce de MACD | +23.25% | +1.78% | 33.3% | 1.55 | -33.98% | 21 |
| Reversión RSI | -50.32% | -18.29% | 33.3% | 0.02 | -53.59% | 3 |

Ninguna estrategia es universalmente mejor: Ruptura Bollinger tiene el mayor
retorno total, pero Cruce de SMA gana en ganancia promedio por transacción
con muchas menos operaciones (5 vs. 10). `trend_confirmation` demuestra el
valor de filtrar señales: comparado con el `macd_crossover` puro sobre el
mismo escenario, reduce operaciones de 21 a 10 y casi duplica el Sharpe
(1.14 vs 0.76), aunque paga por eso en ganancia promedio menor que las dos
primeras. Reversión RSI es la peor en este escenario particular — no
significa que sea mala en general, solo que no encaja con estos regímenes de
mercado. Por eso existe `compare_strategies`/`simulate`/la pantalla web: para
elegir la mejor estrategia por instrumento y periodo, no asumir una sola
ganadora universal.

Corre tu propia comparación:
```bash
python -m app.cli simulate --synthetic --out reporte.json          # sin red
python -m app.cli simulate --symbol AAPL --period 2y                # datos reales
```
o desde la pantalla web (`/`), dejando "Estrategia" en "Todas (comparar)".

## Expectativa vs realidad: resultados

Corriendo las tres validaciones sobre el mismo escenario histórico sintético:

**1. Fuera de muestra** (primera mitad = expectativa, segunda mitad = realidad,
ganancia promedio por operación): en las 5 estrategias, el **signo**
(rentable/no rentable) se mantuvo igual entre ambos periodos — ninguna pasó de
ganar en la primera mitad a perder en la segunda, ni viceversa. La magnitud sí
varía (ej. `sma_crossover` +6.82% → +5.27%, `macd_crossover` +0.03% → +3.71%),
lo cual es normal y esperable — el punto es que ninguna estrategia se "rompió"
al pasar a datos no vistos.

**2. Precisión direccional** (¿la operación acertó la dirección?): `Cruce de
SMA` y `Ruptura Bollinger` aciertan 60% de sus operaciones (mejor que el azar);
`Cruce de MACD` y `Reversión RSI` solo 33.3% (peor que el azar — muchas
operaciones, poca puntería); `Confirmación de tendencia` 40%.

**3. Motor de recomendaciones** (retorno real a 10 días después de cada
llamada): las recomendaciones **SELL** tuvieron 63.6% de acierto (el precio
efectivamente bajó) con retorno promedio -1.35% — la señal bajista funcionó
razonablemente bien en este escenario con una caída fuerte. Las **BUY**
acertaron solo 50% (moneda al aire) con retorno promedio -0.11% — la señal
alcista no fue confiable en este periodo particular. Esto es coherente con el
escenario: tiene una caída fuerte prolongada, terreno favorable para llamadas
bajistas y adverso para las alcistas.

**Conclusión práctica**: ninguna estrategia ni el motor de recomendaciones son
infalibles, y su confiabilidad depende del régimen de mercado. Por eso el
valor real está en poder medir esto por instrumento y periodo (`validate`), no
en confiar ciegamente en una sola señal.

## Instalación

```bash
pip install -r requirements.txt
```

## Uso — CLI

```bash
python -m app.cli strategies
python -m app.cli backtest --symbol AAPL --strategy sma_crossover --period 2y
python -m app.cli compare --symbol BTC-USD --period 1y
python -m app.cli recommend --symbol EURUSD=X --period 1y

# Simulador: datos reales o un escenario sintético (sin red)
python -m app.cli simulate --symbol AAPL --period 3y --strategy macd_crossover
python -m app.cli simulate --synthetic --out reporte.json

# Cualquier comando acepta --no-short para restringir a solo posiciones largas
python -m app.cli backtest --symbol BTC-USD --strategy sma_crossover --no-short

# Simulador con rango de fechas explícito
python -m app.cli simulate --symbol AAPL --start-date 2023-06-01 --end-date 2023-09-30

# Validación: expectativa vs realidad (fuera de muestra + precisión direccional + recomendaciones)
python -m app.cli validate --synthetic --out validacion.json
python -m app.cli validate --symbol AAPL --period 2y --split-ratio 0.6 --horizon 15
```

## Uso — Pantalla web

```bash
uvicorn app.api.main:app --reload
```

Abre `http://localhost:8000/` en el navegador. Tiene dos pestañas:

- **Simulador**: símbolo, **rango de fechas** (desde/hasta), estrategia (o
  "Todas" para comparar) y el switch de posiciones cortas. Si no hay acceso a
  datos de mercado en vivo, marca "Usar escenario sintético" para probar el
  motor con el histórico generado (2023-01-01 a 2023-11-16) — el rango de
  fechas recorta dentro de esa ventana. Muestra precio con señales de
  entrada/salida, curva de capital comparada contra buy&hold, tabla de
  métricas y bitácora de operaciones.
- **Validación**: los mismos parámetros de símbolo/fechas/sintético, más
  opciones avanzadas (% de expectativa, horizonte, separación, calentamiento).
  Muestra las tres validaciones de expectativa vs realidad: barras de
  expectativa/realidad por estrategia (fuera de muestra), precisión
  direccional por estrategia, y el precio con cada llamada del motor de
  recomendaciones marcada como acierto (relleno) o fallo (hueco), con tooltip.

## Uso — API

```bash
uvicorn app.api.main:app --reload
```

- `GET /health`
- `GET /strategies`
- `GET /symbols/examples`
- `GET /recommend/{symbol}?period=2y&interval=1d`
- `POST /backtest` — body: `{"symbol": "AAPL", "strategy": "sma_crossover", "period": "2y", "allow_short": true}`
- `POST /backtest/compare` — body: `{"symbol": "BTC-USD", "period": "1y"}`
- `POST /simulate` — body: `{"symbol": "AAPL", "start_date": "2023-06-01", "end_date": "2023-09-30"}` o `{"synthetic": true, "strategy": "sma_crossover", "start_date": "2023-04-01", "end_date": "2023-09-30"}`
- `POST /validate` — body: `{"symbol": "AAPL", "period": "2y"}` o `{"synthetic": true, "split_ratio": 0.6, "horizon": 15}`

## Estructura del proyecto

```
app/
  config.py            # clases de activos, símbolos de ejemplo
  data/providers.py     # obtención de OHLCV (Yahoo Finance)
  data/synthetic.py      # generador de escenarios históricos sintéticos
  indicators/technical.py
  strategies/           # framework base (long/short) + 5 estrategias concretas
  backtest/             # motor de backtesting + métricas
  recommend/engine.py    # ensemble de recomendaciones
  simulate.py            # simulador (datos reales o sintéticos, con rango de fechas)
  validation/            # expectativa vs realidad: fuera de muestra, precisión
                         # direccional, precisión de recomendaciones
  api/main.py            # FastAPI (sirve también la pantalla web en "/")
  static/index.html       # pantalla web del simulador
  cli.py                 # interfaz de línea de comandos
tests/
```

## Posiciones cortas (shorts)

Todas las estrategias soportan largo **y** corto (`allow_short=True` por
defecto en `Strategy`, `build_strategy`, `all_strategies`, `recommend` y el
simulador); pásale `allow_short=False` (o `--no-short` en el CLO, o
`"allow_short": false` en la API) si el instrumento/cuenta no permite
shortear (ej. cripto spot sin margen) o simplemente no quieres apostar a la
baja.

En el escenario histórico sintético de demo (alza → corrección → lateral →
caída fuerte → recuperación), permitir shorts cambió resultados de forma
significativa para la misma estrategia:

| Estrategia | Retorno total solo-largo | Retorno total largo+corto |
|---|---|---|
| `bollinger_breakout` | +25.2% | **+62.8%** |
| `macd_crossover` | -5.6% | **+23.3%** |
| `sma_crossover` | -10.8% | **+18.8%** |

Sin shorts, esas estrategias se quedan en efectivo durante la caída fuerte y
no capturan nada; con shorts, ese tramo bajista se convierte en ganancia —
justo lo que buscabas con "mayor capacidad de ganancia por transacción".
(`rsi_reversion` perdió dinero en ambos casos en este escenario particular;
no todas las estrategias funcionan igual de bien en todos los regímenes, por
eso existe `compare_strategies`/`simulate` para elegir la mejor por
instrumento.)

## Roadmap

1. **Fase actual — Backtesting y recomendaciones** (este MVP).
2. **Dashboard web** para visualizar equity curves, señales activas y
   comparativas entre instrumentos/estrategias.
3. **Ejecución de órdenes**: integración con un broker/exchange. Dado que
   mueve dinero real, se implementará primero en modo *semi-automático*
   (confirmación manual) con gestión de riesgo (stop-loss, tamaño de
   posición, límites de exposición) antes de considerar ejecución
   totalmente automática.

## Nota sobre el entorno de desarrollo

En el entorno sandbox donde se desarrolló este MVP, la política de red del
contenedor bloquea el acceso saliente a Yahoo Finance
(`fc.yahoo.com` responde 403 en el proxy de egress), por lo que el motor de
datos, indicadores, estrategias, backtester y recomendaciones se validaron
con datos sintéticos (`tests/`). Para usar datos reales, ejecuta la app en un
entorno con acceso a internet sin restricciones a `finance.yahoo.com`.
