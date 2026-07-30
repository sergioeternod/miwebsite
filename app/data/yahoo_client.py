"""Direct client for Yahoo Finance's public chart API — a fallback used when
`yfinance` itself fails.

`yfinance`'s `Ticker.history()` goes through a cookie/crumb authentication
dance (via `curl_cffi`, impersonating a specific browser's TLS fingerprint)
that exists to serve `Ticker.info`, a feature this app never uses. Some
network proxies interfere with that TLS impersonation and reset the
connection outright — this project's own sandboxed dev environment does,
even once its network policy is opened up to allow the host. Yahoo's public
`v8/finance/chart` endpoint returns the same historical OHLCV data over a
plain HTTPS GET, without that flow, so this app can talk to it directly
when `yfinance` fails.
"""

from __future__ import annotations

import re

import pandas as pd
import requests

_BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
_TIMEOUT_SECONDS = 15
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# Yahoo's chart API accepts either a `range` shorthand (from this fixed set)
# or an explicit `period1`/`period2` epoch-second window. Anything outside
# this set (e.g. this app's own "13y") falls back to computing an explicit
# window instead.
_VALID_RANGES = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"}
_PERIOD_RE = re.compile(r"^(\d+)(d|mo|y)$")
_PERIOD_UNIT_DAYS = {"d": 1, "mo": 30, "y": 365}


class YahooUnavailableError(RuntimeError):
    pass


def _period_to_days(period: str) -> int | None:
    match = _PERIOD_RE.match(period)
    if not match:
        return None
    count, unit = match.groups()
    return int(count) * _PERIOD_UNIT_DAYS[unit]


def _build_params(period: str, interval: str, start: str | None, end: str | None) -> dict:
    params = {"interval": interval}
    if start or end:
        start_ts = pd.Timestamp(start) if start else pd.Timestamp("1970-01-01")
        end_ts = pd.Timestamp(end) + pd.Timedelta(days=1) if end else pd.Timestamp.now()
        params["period1"] = int(start_ts.timestamp())
        params["period2"] = int(end_ts.timestamp())
    elif period in _VALID_RANGES:
        params["range"] = period
    else:
        days = _period_to_days(period)
        if days is None:
            raise YahooUnavailableError(f"Periodo '{period}' no reconocido por el cliente directo de Yahoo Finance.")
        params["period1"] = int((pd.Timestamp.now() - pd.Timedelta(days=days)).timestamp())
        params["period2"] = int(pd.Timestamp.now().timestamp())
    return params


def get_ohlcv(
    symbol: str,
    period: str = "2y",
    interval: str = "1d",
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Fetch historical OHLCV directly from Yahoo's chart API.

    Split/dividend-adjusted the same way `yfinance`'s `auto_adjust=True`
    is: `Close` comes from the response's `adjclose` series, and
    Open/High/Low are scaled by that same per-bar adjclose/close ratio so
    each bar stays internally consistent (this is what keeps a stock split
    from showing up as a fake, single-day near-100% crash in the raw price).
    """
    params = _build_params(period, interval, start, end)

    try:
        response = requests.get(
            _BASE_URL.format(symbol=symbol), params=params, headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT_SECONDS
        )
    except requests.RequestException as exc:
        raise YahooUnavailableError(f"No se pudo conectar con Yahoo Finance: {exc}") from exc

    if response.status_code != 200:
        raise YahooUnavailableError(f"Yahoo Finance respondió {response.status_code} para '{symbol}'.")

    try:
        payload = response.json().get("chart", {})
    except ValueError as exc:
        raise YahooUnavailableError(f"Yahoo Finance devolvió una respuesta inesperada para '{symbol}': {exc}") from exc

    error = payload.get("error")
    if error:
        raise YahooUnavailableError(f"Yahoo Finance: {error.get('description', error)}")

    results = payload.get("result") or []
    if not results:
        raise YahooUnavailableError(f"Yahoo Finance no tiene datos para '{symbol}'.")

    result = results[0]
    timestamps = result.get("timestamp")
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    adjclose_series = (result.get("indicators", {}).get("adjclose") or [{}])[0].get("adjclose")
    if not timestamps or not quote.get("close"):
        raise YahooUnavailableError(f"Yahoo Finance no tiene datos para '{symbol}'.")

    gmtoffset = result.get("meta", {}).get("gmtoffset", 0)
    index = (pd.to_datetime(timestamps, unit="s") + pd.Timedelta(seconds=gmtoffset)).normalize()

    df = pd.DataFrame(
        {
            "Open": quote.get("open"),
            "High": quote.get("high"),
            "Low": quote.get("low"),
            "Close": quote.get("close"),
            "Volume": quote.get("volume"),
        },
        index=index,
    )
    df.index.name = "Date"

    if adjclose_series:
        adj = pd.Series(adjclose_series, index=index)
        ratio = (adj / df["Close"]).replace([float("inf"), float("-inf")], pd.NA)
        for col in ("Open", "High", "Low"):
            df[col] = df[col] * ratio
        df["Close"] = adj

    df = df.dropna(subset=["Open", "High", "Low", "Close", "Volume"])

    # Near-24-hour instruments (forex, crypto) can come back with a second,
    # still-forming bar for "today" alongside the regular daily one — both
    # normalize to the same calendar date, since the live bar's timestamp
    # doesn't follow the regular session-close convention the historical
    # bars do. Keep the last (most current) of any such collision rather
    # than let a duplicate date reach callers that assume a unique daily
    # index (e.g. `pd.Series.reindex`, which raises on duplicate labels).
    df = df[~df.index.duplicated(keep="last")]

    if df.empty:
        raise YahooUnavailableError(f"Yahoo Finance no tiene datos utilizables para '{symbol}'.")
    return df
