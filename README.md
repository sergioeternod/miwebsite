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
- **Estrategias** (long-only, sin apalancamiento):
  - `sma_crossover` — seguimiento de tendencia (cruce de medias móviles)
  - `macd_crossover` — seguimiento de tendencia (cruce de MACD/señal)
  - `rsi_reversion` — reversión a la media (rebote confirmado desde sobreventa)
  - `bollinger_breakout` — ruptura de momentum (breakout de banda superior)
- **Motor de backtesting** con métricas por estrategia e instrumento:
  retorno total, CAGR, máximo drawdown, Sharpe ratio, win rate,
  **ganancia promedio por transacción**, mejor/peor operación, profit factor.
  `compare_strategies` rankea las estrategias por ganancia promedio por
  transacción para identificar cuál tiene mayor capacidad de ganancia en un
  instrumento dado.
- **Motor de recomendaciones**: ejecuta todas las estrategias sobre los datos
  más recientes y combina sus señales (BUY/SELL/HOLD) ponderadas por el
  desempeño histórico de cada estrategia en ese instrumento específico,
  devolviendo una recomendación con nivel de confianza y el razonamiento
  técnico detrás.
- **API REST (FastAPI)** y **CLI** para correr backtests y recomendaciones.
- Suite de tests (`pytest`) sobre datos sintéticos, sin depender de red.

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
```

## Uso — API

```bash
uvicorn app.api.main:app --reload
```

- `GET /health`
- `GET /strategies`
- `GET /symbols/examples`
- `GET /recommend/{symbol}?period=2y&interval=1d`
- `POST /backtest` — body: `{"symbol": "AAPL", "strategy": "sma_crossover", "period": "2y"}`
- `POST /backtest/compare` — body: `{"symbol": "BTC-USD", "period": "1y"}`

## Estructura del proyecto

```
app/
  config.py            # clases de activos, símbolos de ejemplo
  data/providers.py     # obtención de OHLCV (Yahoo Finance)
  indicators/technical.py
  strategies/           # framework base + 4 estrategias concretas
  backtest/             # motor de backtesting + métricas
  recommend/engine.py    # ensemble de recomendaciones
  api/main.py            # FastAPI
  cli.py                 # interfaz de línea de comandos
tests/
```

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
