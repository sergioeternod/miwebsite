"""Market data access for stocks, crypto, forex, commodities and indices.

Uses Yahoo Finance (via yfinance) as a single free data source that covers all
of these instrument types under one API, so the rest of the app does not need
per-asset-class integrations for the MVP.
"""

from __future__ import annotations

import pandas as pd
import yfinance as yf


class DataUnavailableError(RuntimeError):
    pass


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    return df


def get_ohlcv(
    symbol: str,
    period: str = "2y",
    interval: str = "1d",
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Fetch historical OHLCV data for any Yahoo Finance symbol.

    If `start` and/or `end` (ISO date strings, e.g. "2023-06-01") are given,
    they take precedence over `period` and fetch that exact date range.

    Returns a DataFrame indexed by date with columns:
    Open, High, Low, Close, Volume
    """
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
