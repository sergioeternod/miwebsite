"""Market data access for stocks, crypto, forex, commodities and indices.

Uses Yahoo Finance as the primary data source, since it covers all of these
instrument types under one free API — first via `yfinance`, falling back to
a direct HTTP client (`app.data.yahoo_client`) against Yahoo's public chart
API if `yfinance` itself fails, since its cookie/crumb authentication flow
(needed only for `Ticker.info`, not for historical OHLCV) doesn't survive
every network proxy. If Yahoo fails outright — both of those, plus a
network policy blocking it, one of its periodic anti-bot outages, or a plain
connectivity error — `get_ohlcv` retries via Stooq (`app.data.stooq_client`),
a second free, no-API-key source with similar multi-asset-class coverage.
Only if all three fail does this raise `DataUnavailableError`, reporting
what each provider said.
"""

from __future__ import annotations

import pandas as pd
import yfinance as yf

from app.data import stooq_client, yahoo_client


class DataUnavailableError(RuntimeError):
    pass


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    return df


def _get_ohlcv_yfinance(
    symbol: str,
    period: str,
    interval: str,
    start: str | None,
    end: str | None,
) -> pd.DataFrame:
    ticker = yf.Ticker(symbol)
    if start or end:
        df = ticker.history(start=start, end=end, interval=interval, auto_adjust=True)
    else:
        df = ticker.history(period=period, interval=interval, auto_adjust=True)

    if df is None or df.empty:
        raise DataUnavailableError(
            f"No se pudo obtener data para el símbolo '{symbol}' "
            f"(start={start}, end={end}, period={period}, interval={interval})."
        )
    df = _flatten_columns(df)
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    df.index.name = "Date"
    return df


def _get_ohlcv_yahoo(
    symbol: str,
    period: str,
    interval: str,
    start: str | None,
    end: str | None,
) -> pd.DataFrame:
    try:
        return _get_ohlcv_yfinance(symbol, period, interval, start, end)
    except Exception as yfinance_exc:
        try:
            return yahoo_client.get_ohlcv(symbol, period=period, interval=interval, start=start, end=end)
        except Exception as direct_exc:
            raise DataUnavailableError(
                f"yfinance falló ({yfinance_exc}) y el cliente directo de Yahoo también falló ({direct_exc})."
            ) from direct_exc


def get_ohlcv(
    symbol: str,
    period: str = "2y",
    interval: str = "1d",
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Fetch historical OHLCV data for `symbol`, using Yahoo Finance's ticker
    conventions (the source both providers are indexed by here).

    If `start` and/or `end` (ISO date strings, e.g. "2023-06-01") are given,
    they take precedence over `period` and fetch that exact date range.

    Falls back to Stooq (see module docstring) if Yahoo fails entirely
    (both `yfinance` and the direct client); raises `DataUnavailableError`
    only if all three do.

    Returns a DataFrame indexed by date with columns:
    Open, High, Low, Close, Volume
    """
    try:
        return _get_ohlcv_yahoo(symbol, period, interval, start, end)
    except Exception as yahoo_exc:
        try:
            return stooq_client.get_ohlcv(symbol, period=period, interval=interval, start=start, end=end)
        except Exception as stooq_exc:
            raise DataUnavailableError(
                f"No se pudo obtener data para '{symbol}': Yahoo Finance falló ({yahoo_exc}) "
                f"y el respaldo Stooq también falló ({stooq_exc})."
            ) from stooq_exc


def filter_date_range(
    df: pd.DataFrame, start_date: str | None = None, end_date: str | None = None
) -> pd.DataFrame:
    """Slice an already-loaded OHLCV DataFrame down to [start_date, end_date]
    (inclusive, ISO date strings). Used to window a synthetic scenario, or any
    other pre-fetched series, without re-hitting the data source."""
    if start_date is None and end_date is None:
        return df
    sliced = df.loc[start_date:end_date]
    if sliced.empty:
        raise DataUnavailableError(
            f"No hay datos entre {start_date or 'el inicio'} y {end_date or 'el final'} de la serie."
        )
    return sliced


def get_latest_price(symbol: str) -> float:
    df = get_ohlcv(symbol, period="5d", interval="1d")
    return float(df["Close"].iloc[-1])


def symbol_exists(symbol: str) -> bool:
    try:
        get_ohlcv(symbol, period="5d", interval="1d")
        return True
    except DataUnavailableError:
        return False
