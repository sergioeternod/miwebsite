"""SEC EDGAR client: point-in-time historical EPS, keyless.

EDGAR's XBRL "company concept" API publishes every EPS figure a company has
filed, WITH the filing date — which is what makes historical P/E honest:
at any past date t we can reconstruct the trailing EPS *as it was publicly
known on that date* (only filings with `filed` <= t), not as it was later
restated. That filing-date gating is the difference between a validatable
fundamental signal and lookahead bias.

Coverage: US filers with XBRL data (roughly 2008-2009 onward). SEC asks for
a descriptive User-Agent with contact info on all requests; no API key.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import date, timedelta

_UA = {"User-Agent": "miwebsite/1.0 (investigacion personal; contacto: sergioe@grupoinsaat.com)"}
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_CONCEPT_URL = "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/EarningsPerShareDiluted.json"
_TIMEOUT = 30

_cik_by_ticker: dict[str, str] | None = None
_eps_cache: dict[str, list[dict]] = {}


class EdgarUnavailableError(RuntimeError):
    """EDGAR couldn't be reached or has no usable data for the symbol."""


def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as response:
        return json.loads(response.read())


def _cik_for(symbol: str) -> str:
    global _cik_by_ticker
    if _cik_by_ticker is None:
        try:
            raw = _get_json(_TICKERS_URL)
        except Exception as exc:
            raise EdgarUnavailableError(f"No se pudo cargar el mapa ticker->CIK de la SEC: {exc}") from exc
        _cik_by_ticker = {entry["ticker"].upper(): str(entry["cik_str"]).zfill(10) for entry in raw.values()}
    cik = _cik_by_ticker.get(symbol.upper())
    if cik is None:
        raise EdgarUnavailableError(f"{symbol} no aparece en el registro de emisoras de la SEC.")
    return cik


def parse_quarterly_eps(entries: list[dict]) -> list[dict]:
    """Reduces raw EDGAR facts to quarterly EPS periods with their first
    public filing date. Handles the standard fiscal-Q4 gap: many companies
    file Q4 only inside the annual 10-K figure, so when a fiscal year has an
    annual value plus exactly three quarterly ones, the missing quarter is
    derived as annual minus the three (dated as known at the 10-K filing).
    For restated periods, the EARLIEST filing wins — that's when the number
    first became public knowledge, which is the causally correct value."""
    quarterly: dict[tuple[str, str], dict] = {}
    annual: list[dict] = []
    for entry in entries:
        start, end, filed, val = entry.get("start"), entry.get("end"), entry.get("filed"), entry.get("val")
        if None in (start, end, filed, val):
            continue
        duration = (date.fromisoformat(end) - date.fromisoformat(start)).days
        record = {"start": start, "end": end, "filed": filed, "eps": float(val)}
        if 60 <= duration <= 120:
            key = (start, end)
            if key not in quarterly or filed < quarterly[key]["filed"]:
                quarterly[key] = record
        elif 330 <= duration <= 380:
            annual.append(record)

    quarters = list(quarterly.values())
    quarter_ends = {q["end"] for q in quarters}
    for year in annual:
        if year["end"] in quarter_ends:
            continue
        inside = [q for q in quarters if year["start"] <= q["start"] and q["end"] <= year["end"]]
        if len(inside) == 3:
            quarters.append(
                {
                    "start": max(q["end"] for q in inside),
                    "end": year["end"],
                    "filed": year["filed"],
                    "eps": round(year["eps"] - sum(q["eps"] for q in inside), 4),
                }
            )
            quarter_ends.add(year["end"])

    quarters.sort(key=lambda q: q["end"])
    return quarters


def get_quarterly_eps(symbol: str) -> list[dict]:
    """Quarterly diluted-EPS history for `symbol` as
    [{"start", "end", "filed", "eps"}], sorted by period end and cached
    in-process. Raises EdgarUnavailableError on network failure or when the
    symbol has no XBRL EPS data."""
    cached = _eps_cache.get(symbol.upper())
    if cached is not None:
        return cached
    cik = _cik_for(symbol)
    try:
        data = _get_json(_CONCEPT_URL.format(cik=cik))
    except Exception as exc:
        raise EdgarUnavailableError(f"No se pudo consultar el EPS histórico de {symbol} en EDGAR: {exc}") from exc
    entries = (data.get("units") or {}).get("USD/shares") or []
    quarters = parse_quarterly_eps(entries)
    if not quarters:
        raise EdgarUnavailableError(f"EDGAR no tiene periodos trimestrales de EPS utilizables para {symbol}.")
    _eps_cache[symbol.upper()] = quarters
    return quarters


def trailing_eps_known_at(quarters: list[dict], as_of: date | str) -> float | None:
    """Trailing-12-month EPS as it was publicly known on `as_of`: the sum of
    the last four distinct quarterly periods whose filings were already
    public (`filed` <= as_of). None when fewer than four quarters were known
    — no number is better than a fabricated one."""
    if isinstance(as_of, str):
        as_of = date.fromisoformat(as_of)
    known = [q for q in quarters if date.fromisoformat(q["filed"]) <= as_of]
    if len(known) < 4:
        return None
    by_end: dict[str, dict] = {}
    for q in known:  # already sorted by end; keep the earliest-filed per end (parse handles dupes)
        by_end.setdefault(q["end"], q)
    ends = sorted(by_end)
    last_four = [by_end[e] for e in ends[-4:]]
    # Guard against gaps: the four quarters should span roughly one year.
    span = date.fromisoformat(last_four[-1]["end"]) - date.fromisoformat(last_four[0]["start"])
    if span > timedelta(days=430):
        return None
    return round(sum(q["eps"] for q in last_four), 4)
