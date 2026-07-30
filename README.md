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
- **Indicadores técnicos**: SMA, EMA, RSI, MACD, Bandas de Bollinger, ATR, ADX
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
- **Comisión realista por tipo de instrumento** (`app/config.py`): si no se
  especifica `commission_bps`, la app ya no asume un 0.05% (5 bps) plano para
  todo — infiere el tipo de instrumento del símbolo y usa un costo "todo
  incluido" (comisión + spread típico) grounded en las plataformas más
  usadas: acciones/índices ~2 bps, forex ~1.5 bps, commodities ~3 bps, cripto
  ~25 bps (los exchanges cripto cobran bastante más que un bróker de
  acciones sin comisión). Ver "Comisión realista por tipo de instrumento" más
  abajo para el detalle y las fuentes. Cualquier llamada puede seguir
  pasando un `commission_bps` explícito para anular el valor automático.
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
- **Overlay de expectativa de resultados (Finnhub)** (`app/fundamentals/earnings.py`):
  opcional (`--with-earnings` / `with_earnings=true`) — usa el historial de
  sorpresas de EPS (real vs. estimado de analistas) de Finnhub para saber si
  la empresa suele superar o fallar expectativas, y cuándo tiene un reporte
  próximo. Si hay un reporte dentro de los próximos 14 días, ajusta (sube o
  baja) la confianza de la recomendación técnica según si el historial de
  sorpresas coincide o contradice la señal técnica — nunca cambia la señal
  BUY/SELL/HOLD en sí. Ver "Recomendaciones con historial de earnings" más
  abajo para configurar el acceso.
- **Overlay de sentimiento de noticias (Alpha Vantage)** (`app/fundamentals/news_sentiment.py`):
  opcional (`--with-news` / `with_news=true`) — mismo mecanismo que el overlay
  de earnings, pero con el "estado de ánimo" general del mercado: usa el
  score de sentimiento por ticker de artículos de noticias recientes de
  Alpha Vantage. Solo ajusta la confianza si hay al menos 3 artículos
  relevantes (≥15% de relevancia al símbolo) y una mayoría clara en una
  dirección — un solo titular aislado no mueve nada. Igual que el de
  earnings, nunca cambia la señal BUY/SELL/HOLD, solo su confianza, con el
  motivo siempre explícito.
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
- **Screener de rentabilidad** (`app/screener.py`): sugiere los símbolos con
  mayor retorno de precio (comprar y mantener, sin depender de ninguna
  estrategia) en la última semana, mes y año. Por defecto escanea el universo
  completo de símbolos de ejemplo (o los 5 perfiles sintéticos sin red) y
  devuelve el top-N por ventana — la vía rápida para "¿qué se está moviendo
  ahora mismo?", antes de entrar a comparar estrategias sobre un símbolo en
  particular.
- **Escáner de oportunidades** (`app/opportunities.py`): a diferencia del
  screener (que rankea por retorno de precio pasado), este corre el motor de
  recomendaciones — técnico + overlays opcionales de earnings/noticias —
  sobre varios símbolos a la vez, y devuelve los que tienen la señal BUY o
  SELL/corto con **mayor confianza ahora mismo**. Responde directamente
  "¿cuáles son los más probables de ganar?" sin tener que ya saber qué
  símbolo consultar. Igual que el resto: universo de ejemplo completo por
  defecto, o perfiles sintéticos sin red.
- **Simulador de portafolio día a día** (`app/portfolio.py`): a partir de una
  fecha de inicio (ej. `2026-01-01`), primero **autoselecciona un portafolio**
  — los símbolos con la señal BUY/SELL más fuerte justo antes de esa fecha,
  usando solo datos anteriores (sin adelantarse al futuro) — y luego **camina
  día por día** hasta el último dato disponible, recalculando la
  recomendación ensemble de cada símbolo con solo la información de ese día
  hacia atrás y ejecutando la compra/venta/mantener resultante como una
  posición simulada. Reporta la curva de capital combinada del portafolio,
  la ganancia/pérdida en dólares total y por símbolo, y la bitácora completa
  de operaciones — la respuesta directa a "corre esto día a día desde tal
  fecha y dime cuánto gané o perdí".
- **Filtro de régimen de mercado (ADX) + umbral de confianza mínima**: el
  ensemble de `recommend()` ajusta el peso de cada estrategia según si el
  mercado está en tendencia fuerte o lateral (favorece trend-following o
  reversión a la media según corresponda, en vez de tratarlas igual siempre),
  y el simulador de portafolio ignora señales BUY/SELL de baja confianza en
  vez de voltear la posición por una lectura casi al azar. Ver "El motor de
  decisión considera el régimen de mercado" más abajo — mejora la calidad de
  la señal, no garantiza ganancias.
- **API REST (FastAPI)** y **CLI** para correr backtests, simulaciones,
  recomendaciones, validaciones, rankings, el screener, el escáner de
  oportunidades, el simulador de portafolio y los overlays de earnings/noticias.
- Suite de tests (`pytest`, 184 casos) sobre datos sintéticos y llamadas HTTP
  simuladas, sin depender de red real — incluye cobertura de posiciones
  largas y cortas, rangos de fecha, las tres validaciones de expectativa vs
  realidad, montos en dólares, el ranking de símbolos, el screener, el
  escáner de oportunidades, el simulador de portafolio, la comisión
  automática por tipo de instrumento, el filtro de régimen de mercado, y los
  overlays de earnings/noticias (con los clientes Finnhub/Alpha Vantage
  mockeados).

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

## Símbolos más rentables (screener)

Corriendo `screen` sobre los 5 perfiles sintéticos, top-3 por ventana (retorno
de precio comprar y mantener, no ligado a ninguna estrategia):

| Ventana | 1º | 2º | 3º |
|---|---|---|---|
| Semana | Mixto (5 regímenes) -0.20% | Tendencia alcista -0.23% | Lateral / rango -0.68% |
| Mes | Mixto (5 regímenes) +17.50% | Tendencia alcista +0.34% | Lateral / rango -1.77% |
| Año | Tendencia alcista +18.30% | Lateral / rango -10.40% | Alta volatilidad -27.33% |

En este escenario el perfil mixto está en plena "recuperación" al final del
histórico (de ahí su +17.5% del último mes pese a ir casi plano en la última
semana), mientras que a un año la tendencia alcista sostenida es la más
rentable — justo lo que se espera de cada perfil por diseño. Con red
disponible, sin pasar símbolos escanea el universo completo de ejemplo:
```bash
python -m app.cli screen --out screener.json
python -m app.cli screen --symbols AAPL,MSFT,TSLA,BTC-USD,ETH-USD,EURUSD=X
```

## Escáner de oportunidades

Distinto del screener: en vez de retorno de precio pasado, corre el motor de
recomendaciones (ensemble de las 5 estrategias) sobre cada símbolo y ordena
por **confianza de la señal actual**. Corriendo `opportunities` sobre los 5
perfiles sintéticos, top-2 por lista:

| Compra | Confianza | Venta en corto | Confianza |
|---|---|---|---|
| Mixto (5 regímenes) | 99.7% | Tendencia bajista sostenida | 95.4% |
| Tendencia alcista sostenida | 97.2% | Lateral / rango | 85.1% |

Esto es justo lo que responde a "¿cuáles son los símbolos más probables de
ganar ahora?" sin tener que indicar de antemano cuál mirar. Con red
disponible, sin pasar símbolos escanea el universo completo de ejemplo, y
acepta los mismos overlays que `recommend`:
```bash
python -m app.cli opportunities --out oportunidades.json
python -m app.cli opportunities --symbols AAPL,MSFT,TSLA,BTC-USD,ETH-USD,EURUSD=X --with-earnings --with-news
```

## Simulador de portafolio día a día

Corriendo `portfolio-sim --synthetic --portfolio-size 2` desde 2026-01-01
(los perfiles sintéticos por defecto tienen ~3 años de "calentamiento" antes
de esa fecha, así que cae justo donde termina el historial previo):

```
Portafolio autoseleccionado (antes de 2026-01-01, sin ver datos futuros):
  Símbolo B (tendencia bajista) → señal SELL, 99.3% de confianza
  Símbolo C (lateral)           → señal SELL, 98.7% de confianza

Periodo simulado: 2026-01-01 → 2026-03-31 (90 días)
Capital inicial: $10,000  →  Capital final: $9,501.97  (-$498.03, -4.98%)
  Símbolo B: $4,861.48 (-$138.52, 2 operaciones, 50% de acierto)
  Símbolo C: $4,640.49 (-$359.51, 2 operaciones, 0% de acierto)
```

Ninguno de los dos perdió apostando exactamente igual que su régimen
"debería" — el ensemble entra y sale varias veces dentro del periodo, no se
queda quieto en un solo lado. Con red disponible, corre exactamente esto
sobre símbolos reales:
```bash
python -m app.cli portfolio-sim --start-date 2026-01-01 --out portafolio.json
python -m app.cli portfolio-sim --start-date 2026-01-01 --symbols AAPL,MSFT,TSLA,BTC-USD,ETH-USD --portfolio-size 3
```
Con `--symbols` real, el periodo `--period` (por defecto `3y`) debe cubrir
`--start-date` más suficiente historial de calentamiento para los
indicadores — el valor por defecto ya lo hace. Nota de rendimiento: cada día
simulado recalcula el ensemble completo (5 estrategias) para cada símbolo
del portafolio, así que periodos largos o portafolios grandes tardan más —
usa `--step N` para recalcular cada N días en vez de todos (más rápido, algo
menos preciso día a día).

### El motor de decisión considera el régimen de mercado y evita sobreoperar

Dos mejoras al ensemble de `recommend()` (afectan también al escáner de
oportunidades y a este simulador, ya que ambos lo usan por debajo):

1. **Filtro de régimen de mercado (ADX)**: las estrategias de tendencia
   (SMA, MACD, Bollinger, confirmación de tendencia) rinden mal en mercados
   laterales/sin tendencia, y la reversión a la media (RSI) rinde mal en
   tendencias fuertes — es un problema conocido de mezclar familias de
   estrategias sin distinguir el régimen actual. Ahora se calcula el ADX
   (fuerza de tendencia, no dirección) sobre los mismos datos y se ajusta el
   peso de cada estrategia según su familia: en tendencia fuerte (ADX alto)
   se refuerzan las de tendencia y se atenúa la reversión; en mercado lateral
   (ADX bajo) es al revés. El ajuste es continuo, no un interruptor brusco.
   La lectura de régimen queda expuesta en `recommend()` como
   `market_regime: {"adx": ..., "reading": "tendencia fuerte" | "rango / sin
   tendencia clara" | "transición"}`.
2. **Umbral de confianza mínima antes de voltear posición** (solo en el
   simulador de portafolio, `--min-confidence`, default 55%): una señal
   BUY/SELL con confianza apenas por encima del azar se trataba igual que
   una señal fuerte, y voltear la posición por una señal débil es
   exactamente lo que convierte un tramo ruidoso en sobreoperación —
   comisión extra más una posición que se revierte justo antes de que lo
   haga el mercado. Ahora una señal por debajo del umbral se trata como
   HOLD (mantiene la posición actual) tanto al seleccionar el portafolio
   como en cada recálculo diario.

**Resultado honesto, no prometido**: en el mismo escenario sintético de
arriba, esto redujo Símbolo C de 3 a 2 operaciones y la pérdida del
portafolio de -$508.60 (-5.09%) a -$498.03 (-4.98%) — una mejora real pero
modesta, no una reversión a ganancia. Con el portafolio completo (5
símbolos) del mismo escenario el resultado fue peor (-$1,137.60, -11.38%),
porque los 5 perfiles sintéticos comparten semilla aleatoria y terminan
correlacionados hacia la misma lectura (todos SELL) justo en esa fecha — un
artefacto de los datos de demostración, no una falla del filtro. Ninguna de
estas dos mejoras garantiza ganar más seguido; existen para que el ensemble
razone mejor sobre el contexto de mercado y ejecute menos operaciones
débiles, nada más.

## Recomendaciones con historial de earnings (Finnhub)

La recomendación técnica (`recommend`) no sabe nada de si una empresa
reportará resultados pronto ni de si suele superar o fallar las expectativas
de los analistas. El overlay de earnings llena ese hueco con datos duros
(sorpresas de EPS históricas), no con sentimiento de noticias por NLP —
evita depender de un modelo de lenguaje para decidir "positivo/negativo" y
en cambio usa el propio track record de la empresa.

**Cómo funciona**: por cada llamada a `recommend --with-earnings`, la app
consulta a Finnhub el historial de EPS real-vs-estimado de las últimas
llamadas de resultados y su próxima fecha de reporte. Si ese reporte cae
dentro de los próximos 14 días:
- Si la empresa **suele superar expectativas** (≥65% de aciertos, sorpresa
  promedio positiva) y la señal técnica es **BUY** → sube la confianza.
- Si **suele fallar expectativas** y la señal técnica es **SELL** → sube la
  confianza (ambas apuntan para el mismo lado).
- Si el historial de earnings **contradice** la señal técnica (ej. suele
  fallar pero la señal es BUY) → baja la confianza, como una alerta.
- Si no hay reporte próximo, o el historial es mixto, no se toca nada.

La señal BUY/SELL/HOLD **nunca cambia** por este overlay — solo su nivel de
confianza, y siempre queda explícito en la respuesta (campo `earnings`) para
qué se ajustó y por qué.

**Configuración**: consigue una API key gratis en [finnhub.io](https://finnhub.io)
y guárdala en tu archivo `.env` local (ver "Configuración de API keys" más
abajo) — luego funciona directo:
```bash
python -m app.cli recommend --symbol AAPL --with-earnings
python -m app.cli earnings --symbol AAPL   # solo el historial de earnings, sin la parte técnica
```
También puedes pasar la key directamente con `--finnhub-key` en vez de usar
`.env`. Sin key configurada (o sin acceso de red a Finnhub), el overlay se
omite de forma controlada — la recomendación técnica se devuelve igual, con
`earnings.available = false` y el motivo.

**Limitación intencional**: esto sirve para la recomendación *en vivo*, no
para backtesting histórico de earnings — para *validar* si "expectativa de
buen reporte → sube" funcionó en el pasado haría falta un archivo histórico
de sorpresas con timestamp exacto por fecha (no solo el estado actual), que
es un dataset aparte. Queda fuera de este alcance inicial.

## Recomendaciones con sentimiento de noticias (Alpha Vantage)

Mismo mecanismo que el overlay de earnings, pero con la señal complementaria:
en vez del historial de resultados de una empresa específica, usa el tono de
las noticias recientes que la mencionan — el "estado de ánimo" general del
mercado sobre ese símbolo ahora mismo.

**Cómo funciona**: `recommend --with-news` consulta a Alpha Vantage los
artículos recientes con un score de sentimiento por ticker (de -1 muy
negativo a +1 muy positivo). Para evitar que un solo titular ruidoso mueva
la aguja, el ajuste solo se aplica si hay:
- Al menos **3 artículos relevantes** (relevancia ≥15% a ese símbolo
  específico, no solo mencionado de pasada), y
- Una **mayoría clara** en una dirección (no solo un promedio ligeramente
  positivo con artículos mitad y mitad).

Si esas condiciones se cumplen y el sentimiento coincide con la señal
técnica → sube la confianza; si la contradice → la baja, como alerta. Igual
que con earnings, la señal BUY/SELL/HOLD **nunca cambia**, y la respuesta
siempre incluye el detalle (`news.rationale`) de cuántos artículos y con qué
tono se usaron para el ajuste.

**Configuración**: consigue una API key gratis en
[alphavantage.co](https://www.alphavantage.co/support/#api-key) y guárdala
en tu `.env` (ver "Configuración de API keys" más arriba):
```bash
python -m app.cli recommend --symbol AAPL --with-news
python -m app.cli news --symbol AAPL   # solo el sentimiento de noticias, sin la parte técnica
```
El tier gratis de Alpha Vantage tiene un límite bajo (25 requests/día en
total, no por símbolo) — si lo agotas, el overlay se omite de forma
controlada (`news.available = false`) igual que sin key configurada.

**Limitación intencional** (igual que earnings): esto es para la
recomendación *en vivo*. Para *validar* si el sentimiento de noticias
predijo bien el movimiento en el pasado haría falta un archivo histórico de
artículos con sentimiento y timestamp exacto — no solo las noticias de hoy —
que también queda fuera de este alcance inicial.

## Instalación

```bash
pip install -r requirements.txt
```

## Configuración de API keys

Las API keys (Finnhub, Alpha Vantage) **nunca van hardcodeadas en el código
ni se commitean al repositorio** — se guardan en un archivo `.env` local, que
ya está en `.gitignore`.

**1. Copia la plantilla y pon tus keys reales:**
```bash
cp .env.example .env
```
Edita `.env` con cualquier editor de texto y complétalo:
```
FINNHUB_API_KEY=tu_key_de_finnhub
ALPHAVANTAGE_API_KEY=tu_key_de_alphavantage
```
La app carga `.env` automáticamente al arrancar (CLI o `uvicorn`) con
`python-dotenv` — no hace falta exportar nada a mano. `FINNHUB_API_KEY`
habilita el overlay de earnings (`--with-earnings`) y `ALPHAVANTAGE_API_KEY`
el de sentimiento de noticias (`--with-news`); cada uno funciona
independiente del otro.

**2. Verifica que quedaron bien:**
```bash
python -m app.cli earnings --symbol AAPL
python -m app.cli news --symbol AAPL
```
Si ves el historial de earnings / las noticias (o un error del proveedor
distinto a "no hay API key configurada"), quedaron bien leídas.

**Alternativas a `.env`** (si prefieres no usar el archivo):
- Pasar la key directamente en cada comando: `--finnhub-key tu_key` /
  `--av-key tu_key`.
- Variable de entorno de la sesión — se pierde al cerrar la terminal:
  - Windows PowerShell: `$env:FINNHUB_API_KEY="tu_key"`
  - Windows CMD: `set FINNHUB_API_KEY=tu_key`
  - macOS/Linux: `export FINNHUB_API_KEY=tu_key`
  (mismo patrón con `ALPHAVANTAGE_API_KEY`)
- Variable de entorno permanente en Windows (persiste entre sesiones):
  `setx FINNHUB_API_KEY "tu_key"` (abre una terminal nueva para que tome efecto).

**Importante**: `.env` es tuyo y local — nunca lo pegues en el chat, nunca lo
subas a git, y si por error llegaras a commitearlo, hay que rotar (regenerar)
esa key desde el sitio del proveedor, no basta con borrarlo del commit.

## Uso — CLI

```bash
python -m app.cli strategies
python -m app.cli backtest --symbol AAPL --strategy sma_crossover --period 2y
python -m app.cli compare --symbol BTC-USD --period 1y
python -m app.cli recommend --symbol EURUSD=X --period 1y

# Recomendación ajustada por historial de earnings (requiere FINNHUB_API_KEY)
python -m app.cli recommend --symbol AAPL --with-earnings
python -m app.cli earnings --symbol AAPL

# Recomendación ajustada por sentimiento de noticias (requiere ALPHAVANTAGE_API_KEY)
python -m app.cli recommend --symbol AAPL --with-news
python -m app.cli news --symbol AAPL

# Ambos overlays a la vez
python -m app.cli recommend --symbol AAPL --with-earnings --with-news

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

# Screener: ¿cuáles son los símbolos más rentables ahora (semana/mes/año)?
python -m app.cli screen --synthetic
python -m app.cli screen --symbols AAPL,MSFT,BTC-USD,EURUSD=X --top-n 10
python -m app.cli screen --out screener.json  # sin --symbols escanea el universo de ejemplo

# Escáner de oportunidades: ¿cuáles símbolos tienen la señal de compra/venta más fuerte ahora?
python -m app.cli opportunities --synthetic
python -m app.cli opportunities --symbols AAPL,MSFT,BTC-USD,EURUSD=X --with-earnings --with-news
python -m app.cli opportunities --out oportunidades.json  # sin --symbols escanea el universo de ejemplo

# Simulador de portafolio día a día: ¿cuánto gané/perdí simulando desde una fecha?
python -m app.cli portfolio-sim --synthetic --start-date 2026-01-01
python -m app.cli portfolio-sim --start-date 2026-01-01 --symbols AAPL,MSFT,TSLA,BTC-USD,ETH-USD --portfolio-size 3
python -m app.cli portfolio-sim --start-date 2026-01-01 --out portafolio.json
python -m app.cli portfolio-sim --start-date 2026-01-01 --min-confidence 65  # más exigente, menos operaciones
```

## Uso — Pantalla web

```bash
uvicorn app.api.main:app --reload
```

Abre `http://localhost:8000/` en el navegador. Tiene cinco pestañas:

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
- **Más rentables**: lista de símbolos separada por coma, vacía para escanear
  el universo de ejemplo completo, o perfiles sintéticos sin red — muestra el
  top-N (configurable) de símbolos con mayor retorno de precio en la última
  semana, mes y año, y qué símbolos no tenían datos suficientes.
- **Recomendación**: tiene dos partes. **"Buscar oportunidades"** escanea
  varios símbolos a la vez (lista separada por coma, universo de ejemplo
  completo si se deja vacío, o perfiles sintéticos sin red) y muestra dos
  tablas — mejores oportunidades de compra y de venta en corto, ordenadas
  por confianza — con un botón "Ver detalle" por fila que salta a la segunda
  parte. **"Consultar un símbolo específico"** (requiere datos reales, no
  tiene modo sintético) muestra la señal BUY/SELL/HOLD del ensemble con su
  confianza, el detalle de cada una de las 5 estrategias, y — con los
  checkboxes de earnings/noticias marcados y API key configurada en el
  servidor — una tarjeta por overlay con su señal, cuánto ajustó la
  confianza, si refuerza o contradice la señal técnica, y el detalle que lo
  respalda. Si falta la API key, la tarjeta lo indica sin bloquear el resto
  de la recomendación.

## Uso — API

```bash
uvicorn app.api.main:app --reload
```

- `GET /health`
- `GET /strategies`
- `GET /symbols/examples`
- `GET /recommend/{symbol}?period=2y&interval=1d&with_earnings=true&with_news=true` — `with_earnings` requiere `FINNHUB_API_KEY`, `with_news` requiere `ALPHAVANTAGE_API_KEY`, ambos configurados en el servidor
- `GET /earnings/{symbol}` — historial de sorpresas de EPS + próxima fecha de reporte (Finnhub); responde 503 si no hay `FINNHUB_API_KEY` configurada
- `GET /news/{symbol}` — sentimiento de noticias recientes (Alpha Vantage); responde 503 si no hay `ALPHAVANTAGE_API_KEY` configurada
- `POST /backtest` — body: `{"symbol": "AAPL", "strategy": "sma_crossover", "period": "2y", "allow_short": true}`
- `POST /backtest/compare` — body: `{"symbol": "BTC-USD", "period": "1y"}`
- `POST /simulate` — body: `{"symbol": "AAPL", "start_date": "2023-06-01", "end_date": "2023-09-30"}` o `{"synthetic": true, "strategy": "sma_crossover", "start_date": "2023-04-01", "end_date": "2023-09-30"}`
- `POST /validate` — body: `{"symbol": "AAPL", "period": "2y"}` o `{"synthetic": true, "split_ratio": 0.6, "horizon": 15}`
- `POST /rank` — body: `{"symbols": ["AAPL", "MSFT", "BTC-USD"], "period": "2y"}` o `{"synthetic": true}`
- `POST /screen` — body: `{"symbols": ["AAPL", "MSFT", "BTC-USD"], "top_n": 10}`, `{"synthetic": true}`, o `{}` (escanea el universo de ejemplo)
- `POST /opportunities` — body: `{"symbols": ["AAPL", "MSFT", "BTC-USD"], "with_earnings": true, "with_news": true, "top_n": 10}`, `{"synthetic": true}`, o `{}` (escanea el universo de ejemplo)
- `POST /simulate-portfolio` — body: `{"start_date": "2026-01-01", "portfolio_size": 3}`, `{"start_date": "2026-01-01", "symbols": ["AAPL", "MSFT", "BTC-USD"]}`, `{"start_date": "2026-01-01", "synthetic": true}`, o con `"min_confidence_pct": 65` para exigir más convicción antes de operar

## Estructura del proyecto

```
app/
  config.py            # clases de activos, símbolos de ejemplo, comisión realista por tipo de instrumento
  data/providers.py     # obtención de OHLCV (Yahoo Finance)
  data/synthetic.py      # generador de escenarios históricos sintéticos
  data/finnhub_client.py  # cliente HTTP de earnings surprises/calendario (Finnhub)
  data/alphavantage_client.py  # cliente HTTP de noticias con sentimiento (Alpha Vantage)
  fundamentals/earnings.py  # resumen + overlay de earnings sobre la recomendación técnica
  fundamentals/news_sentiment.py  # resumen + overlay de sentimiento de noticias
  indicators/technical.py
  strategies/           # framework base (long/short) + 5 estrategias concretas
  backtest/             # motor de backtesting + métricas
  recommend/engine.py    # ensemble de recomendaciones (+ overlay opcional de earnings)
  simulate.py            # simulador (datos reales o sintéticos, con rango de fechas)
  validation/            # expectativa vs realidad: fuera de muestra, precisión
                         # direccional, precisión de recomendaciones
  ranking.py             # comparación estrategia × símbolo
  screener.py            # ranking de rentabilidad por ventana (semana/mes/año)
  opportunities.py       # escáner multi-símbolo del motor de recomendaciones (+ overlays)
  portfolio.py           # simulador de portafolio día a día (autoselección + walk-forward)
  api/main.py            # FastAPI (sirve también la pantalla web en "/")
  static/index.html       # pantalla web (5 pestañas: Simulador/Validación/Símbolos/Más rentables/Recomendación)
  cli.py                 # interfaz de línea de comandos
tests/
```

## Comisión realista por tipo de instrumento

Antes, todo backtest/simulación que no especificara `commission_bps` asumía
un 0.05% (5 bps) plano — sin importar si era una acción, un cripto o un par
de forex. Eso no refleja cómo cobran realmente las plataformas principales,
así que ahora el default depende del tipo de instrumento (`app/config.py`,
`DEFAULT_COMMISSION_BPS` / `infer_asset_class`):

| Tipo de instrumento | Comisión "todo incluido" (ida, bps) | Por qué |
|---|---|---|
| Acciones / índices | 2 | La mayoría de brokers grandes (Schwab, Fidelity, Robinhood, E\*TRADE) cobran $0 de comisión, pero el spread/slippage de una acción líquida sigue costando un par de bps; el pricing por acción de IBKR cae en el mismo rango. |
| Forex | 1.5 | Brokers ECN/spread crudo (Interactive Brokers, Pepperstone) rondan 0.4-0.8 pips todo incluido en EUR/USD; brokers "sin comisión" (eToro, Plus500) compensan con spread más ancho, así que el promedio ponderado entre plataformas queda algo más alto que el ECN puro. |
| Commodities (futuros) | 3 | Comisiones por contrato (ej. brokers tipo NinjaTrader/AMP) equivalen a este rango del nocional para un contrato líquido. |
| Cripto | 25 | Los exchanges centralizados cobran bastante más: Binance/Kraken rondan 10-25 bps taker, y el maker/taker retail de Coinbase (0.4%/0.6%) es aún más alto — el promedio entre plataformas grandes queda muy por encima del costo casi nulo de acciones/forex. |

**Cómo se infiere el tipo de instrumento**: primero busca el símbolo exacto
en el universo de ejemplo (`app/config.py`); si no está ahí, usa la
convención de sufijo de Yahoo Finance — `=X` → forex, `=F` → commodity, `^`
al inicio → índice, `XXX-USD`/`XXX-USDT`/etc. → cripto — y si nada coincide,
asume acción (el default menos agresivo). Esto aplica automáticamente en
CLI, API y pantalla web: si dejas el campo de comisión vacío (o no pasas
`--commission-bps` / `commission_bps` en el body), se usa este valor; si
pones un número explícito, ese número manda siempre.

```bash
# Sin --commission-bps: AAPL usa ~2 bps, BTC-USD usa ~25 bps automáticamente
python -m app.cli simulate --synthetic --symbol AAPL --strategy sma_crossover
python -m app.cli simulate --synthetic --symbol BTC-USD --strategy sma_crossover

# Forzar un valor específico en cualquier comando (anula el automático)
python -m app.cli backtest --symbol BTC-USD --strategy sma_crossover --commission-bps 15
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
(`fc.yahoo.com` responde 403 en el proxy de egress) y, por la misma política,
también bloquea `finnhub.io` y `alphavantage.co`. Por eso el motor de datos,
indicadores, estrategias, backtester y recomendaciones se validaron con
datos sintéticos (`tests/`), y los clientes de Finnhub/Alpha Vantage se
probaron con llamadas HTTP simuladas (`tests/test_finnhub_client.py`,
`tests/test_earnings.py`, `tests/test_alphavantage_client.py`,
`tests/test_news_sentiment.py`) en vez de contra las APIs reales. Para usar
datos reales o los overlays de earnings/noticias, ejecuta la app en un
entorno con acceso a internet sin restricciones a `finance.yahoo.com`,
`finnhub.io` ni `alphavantage.co` (por ejemplo, tu máquina local).
