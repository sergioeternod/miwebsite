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
- **Montos en dólares**: además de porcentajes, cada operación reporta su
  ganancia/pérdida en dólares (`pnl_amount`), y cada estrategia reporta
  ganancia total, ganancia promedio por operación, y mejor/peor operación en
  dólares (asumiendo que se reinvierte el 100% del capital en cada operación,
  una a la vez). Estos montos siempre cuadran exactamente con la curva de
  capital — ver nota técnica más abajo.
- **Ranking símbolo × estrategia** (`app/ranking.py`): corre las 5 estrategias
  sobre varios símbolos a la vez y responde dos preguntas — ¿con qué símbolo
  funciona mejor cada estrategia?, y ¿qué estrategia le conviene a cada
  símbolo? Con datos reales (varios símbolos) o con 5 perfiles de mercado
  sintéticos (alcista, bajista, lateral, volátil, mixto) cuando no hay acceso
  a internet.
- **API REST (FastAPI)** y **CLI** para correr backtests, simulaciones,
  recomendaciones, validaciones y rankings.
- Suite de tests (`pytest`, 77 casos) sobre datos sintéticos, sin depender de
  red — incluye cobertura de posiciones largas y cortas, rangos de fecha, las
  tres validaciones de expectativa vs realidad, montos en dólares, y el
  ranking de símbolos.

## Comparación de las 5 estrategias

Sobre el mismo escenario histórico sintético (alza → corrección → lateral →
caída fuerte → recuperación), rankeadas por ganancia promedio por
transacción:

| Estrategia | Retorno total | Ganancia total ($) | Ganancia/operación | Win rate | Profit factor | Máx. drawdown | Operaciones |
|---|---|---|---|---|---|---|---|
| Ruptura Bollinger | +62.79% | **+$6,279** | **+5.28%** | 60.0% | 5.52 | -13.92% | 10 |
| Cruce de SMA | +18.82% | +$1,882 | +4.53% | 60.0% | 1.91 | -23.06% | 5 |
| Confirmación de tendencia | +30.32% | +$3,032 | +3.08% | 40.0% | 2.24 | -18.64% | 10 |
| Cruce de MACD | +23.25% | +$2,325 | +1.50% | 33.3% | 1.46 | -33.98% | 21 |
| Reversión RSI | -50.32% | -$5,032 | -18.89% | 33.3% | 0.00 | -53.59% | 3 |

(Sobre $10,000 de capital inicial.) Ninguna estrategia es universalmente
mejor: Ruptura Bollinger gana en retorno total, ganancia total en dólares y
ganancia promedio por transacción, pero Cruce de SMA logra un desempeño
similar con la mitad de las operaciones (5 vs. 10). `trend_confirmation`
demuestra el valor de filtrar señales: comparado con el `macd_crossover`
puro sobre el mismo escenario, reduce operaciones de 21 a 10 y casi duplica
el Sharpe (1.14 vs 0.76), aunque paga por eso en ganancia promedio menor que
las dos primeras. Reversión RSI es la peor en este escenario particular — no
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
ganancia promedio por operación): 4 de 5 estrategias mantuvieron el mismo
**signo** de rentabilidad entre ambos periodos (ej. `sma_crossover` +5.37% →
+3.98%, `bollinger_breakout` +5.44% → +5.17%) — la magnitud varía, lo cual es
normal, pero no se "rompieron" al pasar a datos no vistos. `macd_crossover`
pasó de una pérdida marginal (-0.17%) a una ganancia (+3.33%): una mejora, no
un quiebre, pero recuerda que la expectativa no es garantía exacta de la
realidad.

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

## ¿Con qué símbolos funciona mejor cada estrategia?

Corriendo `rank` sobre 5 perfiles de mercado sintéticos (alcista, bajista,
lateral, volátil, mixto — sustitutos de símbolos reales sin acceso de red):

| Estrategia | Mejor símbolo/perfil | Ganancia/operación | Ganancia total ($) |
|---|---|---|---|
| Cruce de SMA | Tendencia bajista sostenida | +7.45% | +$2,815 |
| Cruce de MACD | Mixto (5 regímenes) | +1.50% | +$2,325 |
| Reversión RSI | Alta volatilidad / whipsaw | +4.89% | +$805 |
| Ruptura Bollinger | Mixto (5 regímenes) | +5.28% | +$6,279 |
| Confirmación de tendencia | Mixto (5 regímenes) | +3.08% | +$3,032 |

| Símbolo/perfil | Mejor estrategia | Ganancia/operación |
|---|---|---|
| Tendencia alcista sostenida | Reversión RSI | +3.41% |
| Tendencia bajista sostenida | Cruce de SMA | +7.45% |
| Lateral / rango | Cruce de SMA | +1.14% |
| Alta volatilidad / whipsaw | Reversión RSI | +4.89% |
| Mixto (5 regímenes) | Ruptura Bollinger | +5.28% |

Patrón claro: las estrategias de tendencia (SMA, Bollinger) ganan en mercados
con tendencia sostenida (alcista o bajista) y en el escenario mixto; la
reversión a la media (RSI) gana en mercados de alta volatilidad sin tendencia
clara, donde los extremos realmente revierten. Ninguna estrategia domina en
los 5 perfiles — exactamente por eso `rank` existe: para encontrar, dado un
símbolo real, cuál de las 5 estrategias le conviene, en vez de aplicar la
misma a todo. Con red disponible, corre esto sobre símbolos reales:
```bash
python -m app.cli rank --symbols AAPL,MSFT,TSLA,BTC-USD,ETH-USD,EURUSD=X --period 2y
```

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

# Ranking: ¿con qué símbolo funciona mejor cada estrategia?
python -m app.cli rank --synthetic --out ranking.json
python -m app.cli rank --symbols AAPL,MSFT,BTC-USD,EURUSD=X --period 2y
```

## Uso — Pantalla web

```bash
uvicorn app.api.main:app --reload
```

Abre `http://localhost:8000/` en el navegador. Tiene tres pestañas:

- **Simulador**: símbolo, **rango de fechas** (desde/hasta), estrategia (o
  "Todas" para comparar) y el switch de posiciones cortas. Si no hay acceso a
  datos de mercado en vivo, marca "Usar escenario sintético" para probar el
  motor con el histórico generado (2023-01-01 a 2023-11-16) — el rango de
  fechas recorta dentro de esa ventana. Muestra precio con señales de
  entrada/salida, curva de capital comparada contra buy&hold, tabla de
  métricas (con **montos en dólares**) y bitácora de operaciones (con
  ganancia/pérdida en $ por operación).
- **Validación**: los mismos parámetros de símbolo/fechas/sintético, más
  opciones avanzadas (% de expectativa, horizonte, separación, calentamiento).
  Muestra las tres validaciones de expectativa vs realidad: barras de
  expectativa/realidad por estrategia (fuera de muestra), precisión
  direccional por estrategia, y el precio con cada llamada del motor de
  recomendaciones marcada como acierto (relleno) o fallo (hueco), con tooltip.
- **Símbolos**: lista de símbolos separados por coma (o perfiles sintéticos
  sin red) — corre las 5 estrategias sobre todos y muestra el mejor símbolo
  por estrategia, la mejor estrategia por símbolo, y una matriz completa con
  mapa de calor (verde/rojo) de ganancia promedio por transacción.

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
- `POST /rank` — body: `{"symbols": ["AAPL", "MSFT", "BTC-USD"], "period": "2y"}` o `{"synthetic": true}`

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
  ranking.py             # comparación estrategia × símbolo
  api/main.py            # FastAPI (sirve también la pantalla web en "/")
  static/index.html       # pantalla web (3 pestañas: Simulador/Validación/Símbolos)
  cli.py                 # interfaz de línea de comandos
tests/
```

## Nota técnica: montos en dólares y operaciones en corto

El backtester reinvierte el 100% del capital en una posición a la vez
(nunca fraccionado). El monto en dólares de cada operación (`pnl_amount`) se
deriva de la curva de capital, no de un cálculo de precio aislado — esto
importa porque una posición corta sostenida varios días bajo rebalanceo
diario (la curva de capital) no es matemáticamente idéntica a un simple
"entré a X, salí a Y" (el cálculo ingenuo por precio), por el efecto de
"arrastre por rebalanceo" cuando hay volatilidad día a día. Al derivar
`return_pct` y `pnl_amount` de la curva de capital, la suma de las ganancias
y pérdidas de todas las operaciones siempre cuadra exactamente con el cambio
total de capital — puedes verificarlo tú mismo sumando la columna "Ganancia/
Pérdida ($)" de la bitácora de operaciones contra la "Ganancia total ($)" de
la tabla de métricas.

## Posiciones cortas (shorts)

Todas las estrategias soportan largo **y** corto (`allow_short=True` por
defecto en `Strategy`, `build_strategy`, `all_strategies`, `recommend` y el
simulador); pásale `allow_short=False` (o `--no-short` en el CLI, o
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
