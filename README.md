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

- **Datos multi-instrumento**: Yahoo Finance como fuente principal cubre
  acciones, cripto, divisas, commodities e índices con el mismo formato
  OHLCV, usando el símbolo de cada instrumento (`AAPL`, `BTC-USD`,
  `EURUSD=X`, `GC=F`, `^GSPC`, etc.). `get_ohlcv` prueba primero `yfinance`
  y, si falla (su autenticación de cookie/crumb no sobrevive todos los
  proxies), reintenta con un cliente directo al endpoint público de Yahoo
  (`app/data/yahoo_client.py`, ajustando splits/dividendos igual que
  `auto_adjust=True`). Si Yahoo falla por completo, reintenta contra
  **Stooq** (`app/data/stooq_client.py`), una segunda fuente gratuita sin
  API key con cobertura similar — solo si las tres fallan se reporta un
  error, citando lo que dijo cada una.
- **Indicadores técnicos**: SMA, EMA, RSI, MACD, Bandas de Bollinger, ATR, ADX
  (`app/indicators/technical.py`).
- **Estrategias, long y short** (con flag `allow_short` para restringir a
  solo-largo cuando el instrumento/cuenta no permite shortear, ej. cripto
  spot sin margen):
  - `sma_crossover` — seguimiento de tendencia (cruce de medias móviles)
  - `macd_crossover` — seguimiento de tendencia (cruce de MACD/señal)
  - `rsi_reversion` — reversión a la media (rebote/techo confirmado en RSI,
    con salida en la línea media — ver la nota de auditoría del sesgo short
    más abajo)
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

### Aprendizaje de posiciones pasadas: hindsight y umbral adaptativo

Además de mirar hacia adelante (régimen de mercado, confianza del ensemble),
el simulador ahora también mira hacia atrás, a sus propias operaciones ya
cerradas:

1. **Hindsight por operación** (`app.validation.trade_accuracy.
   annotate_trade_hindsight`): para cada operación cerrada, compara —usando
   solo el precio de entrada y salida, ya conocidos porque la operación ya
   terminó— el resultado real contra las otras dos opciones que existían en
   ese momento (la dirección contraria, o quedarse plano). Cada operación
   queda anotada con `hindsight: {best_direction, regret_pct,
   was_optimal, missed_pnl_amount}`, y `hindsight_summary` agrega esas
   anotaciones por símbolo y por portafolio (`% de operaciones óptimas en
   retrospectiva`, `regret promedio`, `$ dejados sobre la mesa`). Esto es
   estrictamente retrospectivo — no hay forma de conocer el precio de salida
   antes de que ocurra, así que nunca se usa como señal en vivo.
2. **Umbral de confianza adaptativo** (`--no-adaptive-learning` para
   desactivarlo, activo por defecto): en cada punto de decisión del
   walk-forward, antes de actuar, el simulador calcula el hindsight de sus
   últimas operaciones ya cerradas —solo las que cerraron estrictamente
   antes del día actual, nunca información futura— y si el regret promedio
   reciente es alto, sube el umbral de confianza exigido para la próxima
   operación (hasta 20 puntos porcentuales más). Una racha de llamadas que en
   retrospectiva debieron ser la dirección contraria hace que el simulador
   se vuelva más exigente, en vez de repetir el mismo error al mismo umbral.
   Esto ajusta la cautela, no la predicción: no puede convertir una llamada
   equivocada en correcta, solo exigir más convicción para la siguiente.

**Resultado honesto, no prometido**: en un escenario diseñado para
demostrarlo (señales BUY/SELL alternadas justo en el límite de confianza,
sobre una tendencia alcista sostenida, donde el lado SELL pierde
sistemáticamente), el aprendizaje adaptativo detectó la racha perdedora y
redujo las operaciones de 40 a 2, mejorando el capital final de $9,577 a
$14,598 sobre los mismos datos y el mismo umbral base. Pero en el escenario
sintético por defecto de este simulador (`portfolio-sim --synthetic`, con
`--portfolio-size 5` o `2`, al umbral de confianza por defecto), el
resultado con y sin aprendizaje adaptativo fue idéntico ($8,862.40 y
$9,501.97 respectivamente) — las llamadas del ensemble en ese escenario casi
nunca caen justo en la zona límite donde el ajuste importaría. El mecanismo
funciona quirúrgicamente donde hay una racha de calls marginales y
consistentemente malas; no es una garantía de mejora en cualquier
escenario, y aquí se reporta tal cual salió, sin recortar el caso en que no
cambió nada.

### Selección de portafolio ajustada por riesgo, noticias y earnings

`recommend()` ya calculaba, para cada estrategia, su Sharpe ratio y máximo
drawdown históricos (`run_backtest` los computa de todos modos) — pero el
simulador de portafolio solo miraba la confianza del ensemble para elegir
qué símbolos incluir. Ahora la selección (no el recálculo diario, ver
abajo) usa un puntaje ajustado por riesgo:

1. **Estadísticas de riesgo** (siempre activo): la confianza de cada
   candidato se escala por un multiplicador basado en el Sharpe ratio y el
   drawdown máximo histórico de su mejor estrategia — un símbolo con
   confianza técnica alta pero un historial de riesgo agresivo (Sharpe
   bajo, drawdowns profundos) ya no gana automáticamente sobre uno con
   confianza algo menor pero un track record más consistente.
2. **Noticias y earnings** (`--with-earnings`/`--with-news`, igual que
   `opportunities`): ajustan la confianza de cada candidato *solo al
   elegir el portafolio*, usando los mismos overlays de Finnhub/Alpha
   Vantage — solo sirven para acciones individuales (AAPL, MSFT, etc.), no
   para cripto/forex/commodities/índices.

**Por qué esto NO se aplica también en el recálculo diario del
walk-forward**: Finnhub y Alpha Vantage devuelven datos relativos a *ahora*
(el reloj real), sin forma de pedir "cómo se veía esto en tal fecha
pasada". Meterlos en la reevaluación diaria de un backtest de varios años
filtraría noticias/earnings de hoy hacia una decisión fechada años atrás —
lookahead bias real, no un detalle de estilo — además de agotar el límite
gratuito de ambas APIs en un puñado de días simulados. Por eso quedan
donde sí son honestos: eligiendo el portafolio de hoy, no relitigando cada
día pasado de la simulación.

**Resultado honesto, verificado con datos reales**: se recalculó la
selección para el mismo universo y la misma fecha de inicio (2023-07-30)
de la corrida de 3 años de la sección anterior. El ranking por pura
confianza había elegido **CL=F, SI=F, ETH-USD, BTC-USD, ^GSPC** — el
resultado real fue -$2,906.13 (-29.06%), arrastrado sobre todo por los
shorts en BTC-USD (-$1,640.19) y ETH-USD (-$1,693.06), ambos con drawdowns
históricos brutales (-50.34% y -59.66%) que el ranking anterior no
penalizaba. El ranking ajustado por riesgo excluye a los dos: elige
**^GSPC, SI=F, EURUSD=X, CL=F, ^DJI** en su lugar. Corriendo la simulación
completa de 3 años sobre este nuevo portafolio, el resultado real fue
**-$40.35 (-0.4%)** — prácticamente sin pérdidas, sobre el mismo periodo,
mismos datos, misma fecha de inicio. Esto no es un caso construido para
verse bien: es la misma corrida honesta de la sección anterior, repetida
con el único cambio de cómo se elige el portafolio.

Dicho esto — este es un resultado de una corrida sobre un periodo
específico, no una garantía general. El multiplicador de riesgo penaliza
drawdowns profundos y Sharpe bajo, que es exactamente lo que le pasó a
BTC/ETH en este tramo del historial real; en un periodo distinto, o con un
universo distinto, el mismo mecanismo puede no cambiar nada, o incluso
empeorar el resultado si penaliza de más a un símbolo que resultó ganador.

### ¿Es un patrón real o suerte de un solo periodo? Validación en 3 ventanas históricas

Un solo periodo que mejoró no prueba nada por sí solo — podría ser suerte
de ese tramo específico. `scripts/multi_period_validation.py` corre la
misma comparación (selección vieja por confianza vs. nueva ajustada por
riesgo) sobre 3 ventanas de 3 años no solapadas, con datos reales:

| Periodo | Portafolio viejo (confianza) | Resultado viejo | Portafolio nuevo (riesgo) | Resultado nuevo | ¿Mejoró? |
|---|---|---|---|---|---|
| 2017-07-30 → 2020-07-30 | CL=F, ^IXIC, GC=F, ^DJI, ^GSPC | **-43.84%** | AAPL, TSLA, GC=F, AMZN, ^GSPC | **+2.96%** | Sí |
| 2019-07-30 → 2022-07-30 | MSFT, NVDA, ETH-USD, GC=F, SI=F | **+14.62%** | USDMXN=X, GC=F, MSFT, EURUSD=X, NVDA | **-27.83%** | **No** |
| 2023-07-30 → 2026-07-30 | CL=F, SI=F, ETH-USD, BTC-USD, ^GSPC | **-29.21%** | ^GSPC, SI=F, EURUSD=X, CL=F, ^DJI | **-0.44%** | Sí |

**2 de 3 periodos mejoraron — y el que no mejoró explica exactamente por
qué esto no es magia.** En 2019-2022 (el arranque del boom cripto durante
la pandemia), la selección vieja incluyó ETH-USD y le fue de maravilla
(era exactamente el activo volátil que sí pagó). La selección nueva
excluyó a ETH-USD por su historial de drawdowns profundos — el mismo
criterio que evitó el desastre de BTC/ETH en 2023-2026 — y esta vez ese
criterio le costó la ganancia. **El ajuste por riesgo no predice el
futuro: cambia qué tipo de error cometes.** Reduce sistemáticamente la
exposición a activos con drawdowns históricos brutales, lo cual evita
desastres cuando esos activos vuelven a caer fuerte (2/3 de los casos
aquí), pero también te deja fuera cuando esos mismos activos son los que
suben con fuerza. No es "el modelo correcto" en un sentido absoluto — es
una elección de perfil de riesgo (más estable, menos exposición a
sorpresas grandes en ambas direcciones), y aquí se reporta con su costo
real, no solo su beneficio. Ejecuta
`python scripts/multi_period_validation.py` (requiere red, ~30 min) para
reproducir esto con tu propio universo/periodos antes de confiar en esto
con dinero real.

### Tres controles de riesgo más: diversificación, tamaño por volatilidad, stop-loss

El ajuste por riesgo de la sección anterior cambia *cuáles* símbolos entran
al portafolio. Estas tres mejoras adicionales cambian *cuánto* capital le
das a cada uno y *cuándo* lo sacas — todas activas por defecto:

1. **Límite por clase de activo** (`--max-per-asset-class`, default 2 en
   símbolos reales): sin esto, nada impedía que el top-N por puntaje fueran
   dos o tres sabores de la misma apuesta — por ejemplo BTC-USD *y*
   ETH-USD ambos en corto a la vez, que no es diversificación real, es la
   misma apuesta cripto duplicada. El límite obliga a que el resto de los
   cupos del portafolio vengan de otra clase de activo, saltando al
   siguiente mejor candidato en vez de encoger el portafolio. Desactivado
   por defecto en el escenario sintético (las etiquetas como "Símbolo A"
   no tienen una clase de activo real que inferir).
2. **Tamaño de posición por volatilidad — risk parity** (`--equal-weight`
   para desactivarlo y volver a partes iguales): en vez de repartir el
   capital por igual entre los símbolos elegidos, cada posición recibe
   capital inversamente proporcional a su propia volatilidad histórica
   diaria — un instrumento tranquilo (ej. un par de forex mayor) recibe más
   capital que uno salvaje (ej. cripto) por el mismo cupo del portafolio.
   Esto captura *algo* de la subida de un símbolo volátil sin darle la
   misma exposición en dólares que a uno estable, en vez de la elección de
   todo-o-nada de antes (incluirlo a tamaño completo o excluirlo).
3. **Stop-loss por posición** (`--stop-loss-pct`, default 15%;
   `--no-stop-loss` para desactivarlo): se revisa *cada día* (no solo los
   días en que se recalcula la señal) — si una posición pierde más de ese
   porcentaje desde que se abrió, se cierra sin importar lo que diga la
   señal técnica en ese momento. Es la única regla de salida de este
   simulador que no espera a que `recommend()` cambie de opinión.

### ¿Es un patrón real o suerte de un solo periodo? Validación en 5 ventanas históricas

Un solo periodo que mejoró no prueba nada por sí solo — podría ser suerte
de ese tramo específico. `scripts/multi_period_validation.py` compara el
modelo original (selección por pura confianza, capital repartido en
partes iguales, sin stop-loss) contra el modelo con las cuatro mejoras
activas (selección ajustada por riesgo con límite por clase de activo,
tamaño por volatilidad, stop-loss), sobre 5 ventanas de 3 años con datos
reales que cubren regímenes distintos (era cripto temprana, bajista 2018,
boom pandémico, bajista 2022 + recuperación 2023, y el periodo reciente):

| Periodo | Portafolio original | Resultado original | Portafolio con las 4 mejoras | Resultado nuevo | ¿Mejoró? |
|---|---|---|---|---|---|
| 2014-07-30 → 2017-07-30 (era cripto temprana) | NVDA, MSFT, AAPL, USDMXN=X, ^DJI | **-6.22%** | CL=F, ^DJI, USDMXN=X, MSFT, NVDA | **-11.76%** | No |
| 2017-07-30 → 2020-07-30 (bajista/mixto) | CL=F, ^IXIC, GC=F, ^DJI, ^GSPC | **-43.84%** | AAPL, TSLA, GC=F, ^GSPC, ^IXIC | **-2.49%** | Sí |
| 2019-07-30 → 2022-07-30 (covid + recuperación + inicio bajista 2022) | MSFT, NVDA, TSLA, ETH-USD, GC=F | **+35.28%** | USDMXN=X, GC=F, MSFT, EURUSD=X, NVDA | **-18.14%** | No |
| 2021-07-30 → 2024-07-30 (bajista 2022 + recuperación 2023) | CL=F, ^DJI, GBPUSD=X, ^GSPC, MSFT | **-32.16%** | USDJPY=X, GBPUSD=X, ^GSPC, ^DJI, MSFT | **-16.40%** | Sí |
| 2023-07-30 → 2026-07-30 | CL=F, SI=F, ETH-USD, BTC-USD, ^GSPC | **-29.39%** | ^GSPC, SI=F, EURUSD=X, CL=F, ^DJI | **-2.59%** | Sí |

**3 de 5 periodos mejoraron, delta promedio de retorno: +4.99 puntos
porcentuales.** Con 5 muestras esto no alcanza para hablar de
significancia estadística real — es evidencia direccional, no una prueba.
Lo honesto que sí se puede decir: las cuatro mejoras juntas parecen
reducir la magnitud de las peores pérdidas (2017-2020 pasó de -43.84% a
-2.49%; 2021-2024 de -32.16% a -16.40%; 2023-2026 de -29.39% a -2.59%) más
consistentemente de lo que recortan una ganancia grande cuando el
portafolio original acertó de lleno (2019-2022, +35.28% → -18.14%, el peor
caso de los cinco). Es la misma historia de siempre en gestión de riesgo:
suavizar las caídas casi siempre cuesta algo de la subida en los tramos
donde el riesgo sí pagó. 2014-2017 muestra que ni siquiera esa
compensación es automática — ahí el modelo nuevo simplemente salió peor,
sin una historia clara de "protección" detrás (probablemente por el
universo reducido de símbolos con historial disponible tan atrás).

Ejecuta `python scripts/multi_period_validation.py` (requiere red, puede
tardar más de una hora) para reproducir esto con tu propio universo o
periodos antes de confiar en esto con dinero real.

**Re-validación tras el fix del sesgo short en RSI** (sección siguiente):
la misma comparación de 5 periodos, ahora con la estrategia RSI corregida
en *ambos* brazos (lo que cambia entre "original" y "mejorado" es solo la
pila de gestión de riesgo — selección ajustada + límite por clase + risk
parity + stop-loss):

| Periodo | Original (RSI ya corregido) | Con las 4 mejoras | ¿Mejoró? |
|---|---|---|---|
| 2014-07-30 → 2017-07-30 | -23.00% | **-16.96%** | Sí |
| 2017-07-30 → 2020-07-30 | -0.19% | **+7.72%** | Sí |
| 2019-07-30 → 2022-07-30 | +4.47% | **-12.36%** | No |
| 2021-07-30 → 2024-07-30 | -47.51% | **-18.93%** | Sí |
| 2023-07-30 → 2026-07-30 | +0.78% | **+14.99%** | Sí |

**4 de 5 mejoraron, delta promedio +7.98 pp** — más consistente que antes
del fix (3/5, +4.99 pp). Los dos matices que siguen en pie: (1) en
términos absolutos el modelo completo sigue perdiendo dinero en 3 de las
5 ventanas (promedio ≈ -5%) — mejor gestión de riesgo no lo convierte en
una máquina de ganar, solo pierde menos y de vez en cuando gana; y (2)
2019-2022 sigue siendo el punto ciego persistente: la pila conservadora
se pierde el boom cripto/tech cada vez que ese régimen aparece.

### Auditoría del sesgo short: la trampa de la salida en el extremo opuesto

Los shorts fueron la fuente de las peores pérdidas en casi todas las
corridas reales, y el escáner llegó a recomendar 4 SELL de 5 picks en un
mercado que venía subiendo. La auditoría encontró la causa estructural en
`rsi_reversion`: entraba en corto cuando el RSI cruzaba hacia abajo el
nivel 70 (fácil — pasa en cada retroceso de una tendencia alcista), pero
solo salía del corto cuando el RSI rebotaba desde abajo de 30 — algo que
en una tendencia alcista sostenida casi nunca ocurre. Una trampa de un
solo sentido, medida sobre datos reales:

- La estrategia pasaba **65-76% de los días en corto** sobre instrumentos
  que subieron 25-71% en el periodo (^GSPC, GC=F, MSFT, 2 años).
- Un solo corto en oro (GC=F) quedó abierto **374 barras (~1.5 años)** y
  perdió **-46.8%** mientras el oro casi se duplicaba.
- Y como una posición corta rancia vota "SELL" en el ensemble cada día con
  el mismo peso que una señal fresca, el sesgo contaminaba al escáner y al
  simulador completos.

**El fix**: una operación de reversión a la media apuesta a que el precio
*vuelva a la media* — no a que llegue al extremo opuesto. Ahora ambos
lados salen cuando el RSI cruza de regreso su línea media (50), además de
las reversas en los extremos. Con el fix, sobre los mismos datos reales,
la estrategia pasa **~64-69% del tiempo plana** (como corresponde a una
estrategia de setups) y su tiempo en corto cayó de 65-76% a 20-25%.
Regression test: `test_rsi_reversion_short_exits_at_midline_not_opposite_extreme`.

**Impacto medido en la simulación de 3 años** (mismo periodo y datos que
las secciones anteriores): de -0.44% a **+20.68%** (+$2,068.25) — la
primera corrida multi-año en positivo. Con las dos advertencias de
siempre: casi toda la ganancia vino de una sola posición (el long de oro
que la trampa short antes impedía tomar — los otros 4 símbolos perdieron
individualmente), y +20.68% en 3 años sigue muy por debajo de comprar
^GSPC y no hacer nada (+62%) o el oro solo (+108%) en ese mismo periodo.
El fix corrige un defecto lógico objetivo; una corrida en positivo no
demuestra que mejore consistentemente en cualquier periodo.

### Benchmark buy & hold en cada reporte, y asimetría long/short medida

Dos adiciones que salen directo de la evidencia anterior:

1. **`benchmark_buy_hold` en todo reporte del simulador de portafolio**:
   mismos símbolos, mismo reparto de capital, comprados al cierre del
   primer día simulado y nunca tocados (una comisión de entrada). El campo
   `vs_benchmark_pct_points` da la diferencia en puntos porcentuales — si
   es negativa, todo el recálculo diario rindió menos que no hacer nada.
   Está siempre visible porque un "+20%" que pierde contra la pasividad no
   es un logro, y sin este número al lado es fácil autoengañarse.
2. **`short_confidence_premium`** (`--short-premium`, default 0 =
   desactivado): puntos de confianza extra que un SELL necesita para abrir
   un corto — los longs no lo pagan, y un SELL defensivo (cerrar un long
   cuando los shorts están deshabilitados) tampoco. Fundamento medido: en
   las tres corridas reales de 3 años guardadas, los longs ganaron dinero
   en todas (+$2,259 / +$2,495 / +$3,841) y los shorts perdieron en todas
   (-$5,165 / -$2,535 / -$1,773), con win rates de 28-39% incluso a
   confianza de 90%+ — un corto apuesta contra la deriva alcista de largo
   plazo del mercado, no solo contra el símbolo. El default se queda en 0
   hasta validar un valor concreto en varios periodos; las tres corridas
   comparten la misma ventana 2023-2026, así que la evidencia todavía
   puede ser específica de una era alcista.

### Experimento long-only: 5/5 ventanas a favor de eliminar los shorts

La asimetría medida (longs rentables en todas las corridas guardadas,
shorts perdiendo en todas) pedía el experimento más audaz primero: el
mismo modelo completo, misma pila de riesgo, pero con `allow_short=False`
— el caso límite de `short_confidence_premium` → infinito. Resultado sobre
las mismas 5 ventanas de 3 años (`scripts/validate_long_only.py`):

| Periodo | Con shorts | Long-only |
|---|---|---|
| 2014-2017 | -16.96% | **+68.53%** |
| 2017-2020 | +7.72% | **+43.21%** |
| 2019-2022 (boom cripto) | -12.36% | **+46.98%** |
| 2021-2024 | -18.93% | **+23.67%** |
| 2023-2026 | +14.99% | **+48.59%** |

**Long-only ganó en 5 de 5, delta promedio +51.3 pp**, y es la primera
configuración positiva en todas las ventanas (promedio ≈ +46% por
trienio). También resolvió el punto ciego persistente de 2019-2022. Los
shorts no eran una pierna débil del modelo: eran su ancla.

La objeción obvia — "las 5 ventanas viven en 2014-2026, una era alcista;
long-only gana porque la época favorecía comprar" — se sometió a la prueba
de fuego: la ventana **2007-2010**, con la crisis financiera y un desplome
de ~55% del S&P adentro (`python scripts/validate_long_only.py
2007-07-30`). Resultado: con shorts **-42.64%**, long-only **+13.51%**.
La clave es que long-only no significa "siempre comprado" sino "comprado
o en efectivo": el umbral de confianza, el stop-loss y el aprendizaje
adaptativo sacaron al modelo del mercado durante el colapso, mientras que
el brazo con shorts se hundió igual que siempre.

**Con 6 de 6 ventanas a favor (incluida una era de crash), el simulador
de portafolio ahora es long-only por defecto** (`allow_short=False` en
`simulate_portfolio_real`/`simulate_portfolio_synthetic` y en la API;
`--with-shorts` en la CLI para reactivarlos). El resto de los comandos
(`backtest`, `recommend`, `opportunities`) conservan los shorts
disponibles — la evidencia es específica del simulador de portafolio, y
el escáner sigue reportando el lado SELL como información. Y la
advertencia de siempre, que ninguna racha de validaciones elimina: 6
ventanas históricas no garantizan la séptima.

### Registro de señales hacia adelante (`track`): la única evidencia sin retrovisor

Todas las validaciones anteriores son backtests — calculadas después de los
hechos, sobre ventanas que también se usaron para ajustar el modelo, así
que cada mejora adicional "validada" ahí carga un riesgo creciente de
sobreajuste. El comando `track` construye el único tipo de evidencia
inmune a eso: señales anotadas *antes* de que exista el resultado.

```bash
python -m app.cli track log                  # registra las señales BUY/SELL de hoy en signals_log.jsonl
python -m app.cli track report --horizon 10  # califica las señales pasadas contra lo que hizo el precio después
```

- `track log` guarda el escaneo del día (deduplicado por fecha de mercado)
  en un JSONL pensado para commitearse al repositorio — las sesiones que lo
  escriben corren en contenedores efímeros, y un log sin commitear muere
  con el contenedor.
- `track report` califica cada señal que ya tiene `--horizon` barras de
  historia posterior: un BUY acierta si el precio subió, un SELL si bajó.
  Reporta hit rate y retorno promedio por lado; las señales muy recientes
  quedan `pending` en vez de calificarse a medias.
- Un modelo que se ve bien en backtests y mediocre en su propio registro
  hacia adelante está sobreajustado — este archivo es donde ese veredicto
  se acumula, un día de mercado a la vez.

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
python -m app.cli portfolio-sim --start-date 2026-01-01 --no-adaptive-learning  # desactiva el ajuste por hindsight
python -m app.cli portfolio-sim --start-date 2026-01-01 --with-earnings --with-news  # ajusta la selección con Finnhub/Alpha Vantage
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
  data/providers.py     # obtención de OHLCV (Yahoo Finance vía yfinance -> cliente directo -> Stooq)
  data/yahoo_client.py    # cliente directo al endpoint público de Yahoo si yfinance falla
  data/stooq_client.py    # respaldo OHLCV sin API key (Stooq) si Yahoo falla por completo
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

Gran parte de este MVP se desarrolló en un entorno sandbox cuya política de
red bloqueaba **todo** el tráfico saliente a proveedores externos de datos
de mercado por igual — no era algo específico de Yahoo: se confirmó
probando `fc.yahoo.com`, `stooq.com`, `www.alphavantage.co` y `finnhub.io`,
los cuatro respondían 403 en el proxy de egress. Por eso el motor de datos,
indicadores, estrategias, backtester y recomendaciones se validaron con
datos sintéticos (`tests/`), y los clientes de Stooq/Yahoo directo/Finnhub/
Alpha Vantage se probaron con llamadas HTTP simuladas (`tests/test_stooq_client.py`,
`tests/test_yahoo_client.py`, `tests/test_providers.py`,
`tests/test_finnhub_client.py`, `tests/test_earnings.py`,
`tests/test_alphavantage_client.py`, `tests/test_news_sentiment.py`) en vez
de contra las APIs reales.

Al habilitar después una política de red más abierta en ese mismo entorno,
apareció un segundo problema, esta vez específico de `yfinance`: su llamado
a `Ticker.history()` pasa primero por una autenticación de cookie/crumb (vía
`curl_cffi`, imitando la huella TLS de un navegador) que existe solo para
`Ticker.info` — algo que esta app nunca usa — y esa imitación no sobrevive
todos los proxies (este entorno, entre ellos: la conexión se resetea en
seco). El endpoint público `v8/finance/chart` de Yahoo devuelve exactamente
los mismos datos históricos con un GET HTTPS plano, sin esa autenticación,
así que `app/data/yahoo_client.py` habla directo con ese endpoint como
segundo intento cuando `yfinance` falla (ajustando splits/dividendos con el
mismo criterio que `auto_adjust=True`, vía el campo `adjclose` de la
respuesta). Con ese respaldo, los datos reales sí funcionan en este mismo
entorno una vez abierta la política de red — se verificó trayendo AAPL,
BTC-USD, EURUSD=X, GC=F y ^GSPC de verdad, uno por cada clase de activo.

Si tu entorno bloquea salida a internet o solo permite un allowlist de
paquetes de desarrollo (`fc.yahoo.com`, `stooq.com`, `finnhub.io`,
`alphavantage.co` fuera de ese allowlist), vas a necesitar una política de
red más abierta para usar datos reales o los overlays de earnings/noticias
— en Claude Code on the web esto se configura por entorno, no por sesión
(ver el selector de entorno en la fila sobre la caja de mensaje en
[claude.ai/code](https://claude.ai/code), y
[la documentación de cloud environments](https://code.claude.com/docs/en/cloud-environments#network-access)
para el detalle de niveles de acceso).
