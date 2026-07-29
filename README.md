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
- **API REST (FastAPI)** y **CLI** para correr backtests, simulaciones y
  recomendaciones.
- Suite de tests (`pytest`, 53 casos) sobre datos sintéticos, sin depender de
  red — incluye cobertura de posiciones largas y cortas, y de rangos de fecha.

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
```

## Uso — Pantalla web (simulador)

```bash
uvicorn app.api.main:app --reload
```

Abre `http://localhost:8000/` en el navegador: formulario con símbolo,
**rango de fechas** (desde/hasta), estrategia (o "Todas" para comparar) y el
switch de posiciones cortas. Si no hay acceso a datos de mercado en vivo,
marca "Usar escenario sintético" para probar el motor con el histórico
generado (2023-01-01 a 2023-11-16) — el rango de fechas recorta dentro de esa
ventana. Muestra precio con señales de entrada/salida, curva de capital
comparada contra buy&hold, tabla de métricas y bitácora de operaciones.

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
