"""Keyless Yahoo Finance quoteSummary client for valuation fundamentals.

Yahoo's v10 quoteSummary endpoint requires a session cookie plus a "crumb"
token; both are obtainable without an API key (visit fc.yahoo.com to seed
the cookie, then ask v1/test/getcrumb). The cookie/crumb pair is cached at
module level and refreshed once on the first 401 — Yahoo rotates them
occasionally.

This deliberately fetches only *current* fundamentals (trailing/forward
P/E, trailing EPS). There is no "as of a past date" parameter, which is
exactly why valuation can only ever be a now-only overlay in this app —
never an input to historical walk-forwards (see app.fundamentals.valuation).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_QUOTE_SUMMARY_URL = "https://query1.finance.yahoo.com/v10/finance/quoteSummary/{symbol}"
_CRUMB_URL = "https://query1.finance.yahoo.com/v1/test/getcrumb"
_COOKIE_SEED_URL = "https://fc.yahoo.com"
_TIMEOUT_SECONDS = 20

_opener: urllib.request.OpenerDirector | None = None
_crumb: str | None = None
_profile_cache: dict[str, dict] = {}
_calendar_cache: dict[str, dict] = {}


class QuoteSummaryUnavailableError(RuntimeError):
    """Yahoo's quoteSummary endpoint couldn't be reached or had no data."""


def _fresh_session() -> tuple[urllib.request.OpenerDirector, str]:
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
    opener.addheaders = [("User-Agent", _USER_AGENT)]
    try:
        opener.open(_COOKIE_SEED_URL, timeout=_TIMEOUT_SECONDS)
    except Exception:
        pass  # fc.yahoo.com responds 404 but still seeds the session cookie
    crumb = opener.open(_CRUMB_URL, timeout=_TIMEOUT_SECONDS).read().decode().strip()
    if not crumb or "<html" in crumb.lower():
        raise QuoteSummaryUnavailableError("Yahoo no entregó un crumb de sesión válido.")
    return opener, crumb


def _raw(field: dict | None) -> float | None:
    if isinstance(field, dict):
        value = field.get("raw")
        return float(value) if isinstance(value, (int, float)) else None
    return None


def get_valuation_metrics(symbol: str) -> dict:
    """Current valuation fundamentals for `symbol`:
    {"trailing_pe", "forward_pe", "trailing_eps"} — each may be None when
    Yahoo has no figure (e.g. loss-making companies have no trailing P/E).
    Raises QuoteSummaryUnavailableError on network/endpoint failure."""
    global _opener, _crumb
    if _opener is None or _crumb is None:
        _opener, _crumb = _fresh_session()

    url = (
        _QUOTE_SUMMARY_URL.format(symbol=urllib.parse.quote(symbol))
        + "?modules=summaryDetail,defaultKeyStatistics,earningsTrend&crumb="
        + urllib.parse.quote(_crumb)
    )
    try:
        try:
            payload = json.loads(_opener.open(url, timeout=_TIMEOUT_SECONDS).read())
        except urllib.error.HTTPError as exc:
            if exc.code == 401:  # crumb rotated — refresh once and retry
                _opener, _crumb = _fresh_session()
                url = url.rsplit("crumb=", 1)[0] + "crumb=" + urllib.parse.quote(_crumb)
                payload = json.loads(_opener.open(url, timeout=_TIMEOUT_SECONDS).read())
            else:
                raise
    except Exception as exc:
        raise QuoteSummaryUnavailableError(f"No se pudo consultar quoteSummary para {symbol}: {exc}") from exc

    results = (payload.get("quoteSummary") or {}).get("result") or []
    if not results:
        raise QuoteSummaryUnavailableError(f"Yahoo no devolvió datos de valuación para {symbol}.")
    summary = results[0].get("summaryDetail") or {}
    key_stats = results[0].get("defaultKeyStatistics") or {}
    trend_rows = ((results[0].get("earningsTrend") or {}).get("trend")) or []
    estimates = {}
    for row in trend_rows:
        period = row.get("period")
        if period in ("0y", "+1y"):
            est = row.get("earningsEstimate") or {}
            eps_trend = row.get("epsTrend") or {}
            estimates[period] = {
                "eps_avg": _raw(est.get("avg")),
                "num_analysts": _raw(est.get("numberOfAnalysts")),
                "eps_avg_90d_ago": _raw(eps_trend.get("90daysAgo")),
            }
    return {
        "trailing_pe": _raw(summary.get("trailingPE")),
        "forward_pe": _raw(summary.get("forwardPE")),
        "trailing_eps": _raw(key_stats.get("trailingEps")),
        "previous_close": _raw(summary.get("previousClose")),
        "estimates": estimates,
    }


def get_asset_profile(symbol: str) -> dict:
    """Sector/industry classification for `symbol` (Yahoo assetProfile),
    cached in-process: {"sector": str | None, "industry": str | None}.
    Raises QuoteSummaryUnavailableError on endpoint failure."""
    cached = _profile_cache.get(symbol.upper())
    if cached is not None:
        return cached
    global _opener, _crumb
    if _opener is None or _crumb is None:
        _opener, _crumb = _fresh_session()
    url = (
        _QUOTE_SUMMARY_URL.format(symbol=urllib.parse.quote(symbol))
        + "?modules=assetProfile&crumb="
        + urllib.parse.quote(_crumb)
    )
    try:
        try:
            payload = json.loads(_opener.open(url, timeout=_TIMEOUT_SECONDS).read())
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                _opener, _crumb = _fresh_session()
                url = url.rsplit("crumb=", 1)[0] + "crumb=" + urllib.parse.quote(_crumb)
                payload = json.loads(_opener.open(url, timeout=_TIMEOUT_SECONDS).read())
            else:
                raise
    except Exception as exc:
        raise QuoteSummaryUnavailableError(f"No se pudo consultar el perfil de {symbol}: {exc}") from exc
    results = (payload.get("quoteSummary") or {}).get("result") or []
    profile = (results[0].get("assetProfile") or {}) if results else {}
    out = {"sector": profile.get("sector"), "industry": profile.get("industry")}
    _profile_cache[symbol.upper()] = out
    return out


def get_calendar_events(symbol: str) -> dict:
    """Próximas fechas de reporte de resultados para `symbol` (Yahoo
    calendarEvents), cacheado in-process: {"earnings_dates": [iso, ...]}.
    Yahoo suele devolver una ventana de 1-2 fechas candidatas. Raises
    QuoteSummaryUnavailableError on endpoint failure."""
    cached = _calendar_cache.get(symbol.upper())
    if cached is not None:
        return cached
    global _opener, _crumb
    if _opener is None or _crumb is None:
        _opener, _crumb = _fresh_session()
    url = (
        _QUOTE_SUMMARY_URL.format(symbol=urllib.parse.quote(symbol))
        + "?modules=calendarEvents&crumb="
        + urllib.parse.quote(_crumb)
    )
    try:
        try:
            payload = json.loads(_opener.open(url, timeout=_TIMEOUT_SECONDS).read())
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                _opener, _crumb = _fresh_session()
                url = url.rsplit("crumb=", 1)[0] + "crumb=" + urllib.parse.quote(_crumb)
                payload = json.loads(_opener.open(url, timeout=_TIMEOUT_SECONDS).read())
            else:
                raise
    except Exception as exc:
        raise QuoteSummaryUnavailableError(f"No se pudo consultar el calendario de {symbol}: {exc}") from exc
    from datetime import datetime, timezone

    results = (payload.get("quoteSummary") or {}).get("result") or []
    earnings = ((results[0].get("calendarEvents") or {}).get("earnings") or {}) if results else {}
    dates = []
    for d in earnings.get("earningsDate") or []:
        raw = d.get("raw") if isinstance(d, dict) else None
        if raw:
            dates.append(datetime.fromtimestamp(int(raw), tz=timezone.utc).date().isoformat())
    out = {"earnings_dates": sorted(set(dates))}
    _calendar_cache[symbol.upper()] = out
    return out
