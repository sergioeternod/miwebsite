"""Screener: ranks symbols by trailing price return over week/month/year
windows — proactive "which symbols are hottest right now" discovery,
independent of any strategy. Indicators can't warm up on a 5- or 21-bar
window, so this uses plain buy & hold return per window instead of a
backtest.
"""

from __future__ import annotations

import pandas as pd

from app.config import EXAMPLE_SYMBOLS
from app.data.providers import get_ohlcv
from app.data.synthetic import generate_ohlcv
from app.ranking import DEFAULT_SYMBOL_PROFILES

WINDOWS = {"semana": 5, "mes": 21, "año": 252}


def _windowed_returns(df: pd.DataFrame) -> dict[str, float | None]:
    close = df["Close"]
    n = len(close)
    returns: dict[str, float | None] = {}
    for label, bars in WINDOWS.items():
        if n <= bars:
            returns[label] = None
            continue
        start_price = float(close.iloc[-bars - 1])
        end_price = float(close.iloc[-1])
        returns[label] = round((end_price / start_price - 1) * 100, 2)
    return returns


def _default_symbols() -> list[str]:
    return [entry["symbol"] for symbols in EXAMPLE_SYMBOLS.values() for entry in symbols]


def _build_report(returns_by_symbol: dict[str, dict], errors: dict[str, str], top_n: int) -> dict:
    top_by_window = {}
    for label in WINDOWS:
        ranked = sorted(
            (
                {"symbol": symbol, "return_pct": windows[label]}
                for symbol, windows in returns_by_symbol.items()
                if windows[label] is not None
            ),
            key=lambda r: r["return_pct"],
            reverse=True,
        )
        top_by_window[label] = ranked[:top_n]

    return {
        "windows": WINDOWS,
        "returns_by_symbol": returns_by_symbol,
        "top_by_window": top_by_window,
        "errors": errors,
    }


def screen_real_symbols(
    symbols: list[str] | None = None,
    period: str = "2y",
    interval: str = "1d",
    top_n: int = 5,
) -> dict:
    """Rank real Yahoo Finance symbols by trailing return over week/month/year.

    Defaults to the app's example-symbol universe (stocks, crypto, forex,
    commodities, indices) when no list is given, so it can proactively
    suggest symbols rather than requiring the caller to already know which
    ones to check.
    """
    symbols = symbols or _default_symbols()

    returns_by_symbol = {}
    errors = {}
    for symbol in symbols:
        try:
            df = get_ohlcv(symbol, period=period, interval=interval)
        except Exception as exc:  # data provider/network failures are per-symbol, not fatal for the whole screen
            errors[symbol] = str(exc)
            continue
        returns_by_symbol[symbol] = _windowed_returns(df)

    return _build_report(returns_by_symbol, errors, top_n)


def screen_synthetic(
    profiles: list[dict] | None = None,
    seed: int = 42,
    top_n: int = 5,
) -> dict:
    """Same ranking, but over synthetic market-character profiles — usable
    with no network access, mirroring app.ranking's synthetic fallback."""
    profiles = profiles or DEFAULT_SYMBOL_PROFILES

    returns_by_symbol = {}
    for profile in profiles:
        df = generate_ohlcv(regimes=profile["regimes"], seed=seed)
        returns_by_symbol[profile["label"]] = _windowed_returns(df)

    return _build_report(returns_by_symbol, {}, top_n)
