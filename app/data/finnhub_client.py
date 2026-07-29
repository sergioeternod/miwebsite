"""Thin client for Finnhub's earnings endpoints.

Finnhub's free tier includes historical EPS "surprises" (actual vs. analyst
estimate per reported quarter) and an earnings calendar — exactly the
"expectation of a good/bad report" signal, as hard numbers instead of NLP
sentiment. Get a free API key at https://finnhub.io and set it as the
FINNHUB_API_KEY environment variable.
"""

from __future__ import annotations

import os

import requests

_BASE_URL = "https://finnhub.io/api/v1"
_TIMEOUT_SECONDS = 10


class FinnhubUnavailableError(RuntimeError):
    pass


def _api_key(api_key: str | None) -> str:
    key = api_key or os.environ.get("FINNHUB_API_KEY")
    if not key:
        raise FinnhubUnavailableError(
            "No hay API key de Finnhub configurada. Consigue una gratis en "
            "https://finnhub.io y pásala con --finnhub-key o la variable de "
            "entorno FINNHUB_API_KEY."
        )
    return key


def _get(path: str, params: dict, api_key: str | None) -> dict | list:
    params = {**params, "token": _api_key(api_key)}
    try:
        response = requests.get(f"{_BASE_URL}{path}", params=params, timeout=_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise FinnhubUnavailableError(f"No se pudo conectar con Finnhub: {exc}") from exc

    if response.status_code != 200:
        raise FinnhubUnavailableError(
            f"Finnhub respondió {response.status_code} para {path}: {response.text[:200]}"
        )
    return response.json()


def get_earnings_surprises(symbol: str, api_key: str | None = None, limit: int = 8) -> list[dict]:
    """Historical EPS actual-vs-estimate per reported quarter, most recent first.

    Each entry: {"period", "quarter", "year", "actual", "estimate", "surprise", "surprisePercent"}.
    `actual`/`surprise`/`surprisePercent` are None for quarters not yet reported.
    """
    data = _get("/stock/earnings", {"symbol": symbol, "limit": limit}, api_key)
    if not isinstance(data, list):
        raise FinnhubUnavailableError(f"Respuesta inesperada de Finnhub para earnings de '{symbol}'.")
    return data


def get_earnings_calendar(symbol: str, from_date: str, to_date: str, api_key: str | None = None) -> list[dict]:
    """Upcoming/past scheduled earnings dates for a symbol in [from_date, to_date] (ISO dates)."""
    data = _get("/calendar/earnings", {"symbol": symbol, "from": from_date, "to": to_date}, api_key)
    if not isinstance(data, dict) or "earningsCalendar" not in data:
        raise FinnhubUnavailableError(f"Respuesta inesperada de Finnhub para el calendario de '{symbol}'.")
    return data["earningsCalendar"]
