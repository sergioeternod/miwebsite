"""Fallback OHLCV provider via Stooq's free CSV export — no API key needed.

Used only when the primary provider (Yahoo Finance, via yfinance) fails: a
network policy blocking Yahoo specifically, one of Yahoo's periodic
anti-bot/cookie-crumb outages, or a plain network error. Stooq covers the
same broad set of asset classes (stocks, indices, forex, commodities,
crypto) for free without an API key, at the cost of a different, less
standard symbol format that has to be translated from Yahoo-style symbols
(see `to_stooq_symbol`).

The stock/forex/crypto/futures mappings below follow Stooq's documented,
stable conventions. The index overrides (`^GSPC`, `^IXIC`, `^DJI`) are
Stooq's own symbols for those three specific indices and don't follow an
algorithmic pattern — if Stooq ever renames them, `get_ohlcv` below will
surface a clear "sin datos" error rather than silently returning the wrong
instrument, since a missing/renamed symbol comes back as an empty response,
not another ticker's data.
"""

from __future__ import annotations

import io
import re

import pandas as pd
import requests

_BASE_URL = "https://stooq.com/q/d/l/"
_TIMEOUT_SECONDS = 15

_INDEX_OVERRIDES = {
    "^GSPC": "^spx",
    "^IXIC": "^ndq",
    "^DJI": "^dji",
}

_PERIOD_RE = re.compile(r"^(\d+)(d|mo|y)$")
_PERIOD_UNIT_DAYS = {"d": 1, "mo": 30, "y": 365}


class StooqUnavailableError(RuntimeError):
    pass


def to_stooq_symbol(yahoo_symbol: str) -> str:
    """Best-effort translation of a Yahoo Finance ticker to Stooq's format.

    - Forex (`EURUSD=X` -> `eurusd`), futures/commodities (`GC=F` -> `gc.f`)
      and crypto (`BTC-USD` -> `btcusd`) follow documented Stooq conventions.
    - The three indices in `app.config.EXAMPLE_SYMBOLS` use `_INDEX_OVERRIDES`
      since there's no algorithmic mapping for index tickers.
    - Anything else is treated as a plain stock and gets Stooq's `.us` suffix
      — correct for this app's example universe (all US-listed), but not a
      general rule for tickers listed on other exchanges.
    """
    symbol = yahoo_symbol.strip()
    if symbol in _INDEX_OVERRIDES:
        return _INDEX_OVERRIDES[symbol]
    if symbol.endswith("=X"):
        return symbol[:-2].lower()
    if symbol.endswith("=F"):
        return symbol[:-2].lower() + ".f"
    if symbol.endswith("-USD"):
        return symbol[:-4].lower() + "usd"
    return symbol.lower() + ".us"


def _period_to_days(period: str) -> int | None:
    """Mirrors yfinance's period shorthand (e.g. "2y", "6mo", "5d") well
    enough for this app's own usage. `None` (e.g. "max") means no cutoff —
    Stooq's CSV export already returns full history."""
    match = _PERIOD_RE.match(period)
    if not match:
        return None
    count, unit = match.groups()
    return int(count) * _PERIOD_UNIT_DAYS[unit]


def get_ohlcv(
    symbol: str,
    period: str = "2y",
    interval: str = "1d",
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Fetch historical OHLCV from Stooq for a Yahoo-style `symbol`. Stooq's
    free CSV export is daily-only, matching this app's `interval="1d"`
    default; any other interval fails fast instead of silently returning
    the wrong granularity."""
    if interval != "1d":
        raise StooqUnavailableError(f"Stooq solo soporta datos diarios (interval='1d'), no '{interval}'.")

    stooq_symbol = to_stooq_symbol(symbol)
    try:
        response = requests.get(_BASE_URL, params={"s": stooq_symbol, "i": "d"}, timeout=_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise StooqUnavailableError(f"No se pudo conectar con Stooq: {exc}") from exc

    text = response.text.strip()
    if response.status_code != 200 or not text or text.lower().startswith("no data"):
        raise StooqUnavailableError(f"Stooq no tiene datos para '{symbol}' (mapeado a '{stooq_symbol}').")

    df = pd.read_csv(io.StringIO(text), parse_dates=["Date"])
    if df.empty or "Close" not in df.columns:
        raise StooqUnavailableError(f"Stooq no tiene datos para '{symbol}' (mapeado a '{stooq_symbol}').")

    df = df.set_index("Date").sort_index()
    df.index.name = "Date"
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()

    if start or end:
        df = df.loc[start:end]
    else:
        days = _period_to_days(period)
        if days is not None and not df.empty:
            cutoff = df.index.max() - pd.Timedelta(days=days)
            df = df[df.index >= cutoff]

    if df.empty:
        raise StooqUnavailableError(
            f"Stooq tiene datos para '{symbol}' (mapeado a '{stooq_symbol}') pero ninguno en el rango pedido."
        )
    return df
