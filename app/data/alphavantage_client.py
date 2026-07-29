"""Thin client for Alpha Vantage's News & Sentiment API.

Alpha Vantage tags recent news articles with an overall sentiment score plus
a per-ticker sentiment breakdown — the general "market mood" signal, as
opposed to Finnhub's earnings-surprise history (app.data.finnhub_client),
which is specifically about quarterly results. Get a free API key at
https://www.alphavantage.co/support/#api-key and set it as the
ALPHAVANTAGE_API_KEY environment variable.
"""

from __future__ import annotations

import os

import requests

_BASE_URL = "https://www.alphavantage.co/query"
_TIMEOUT_SECONDS = 15


class AlphaVantageUnavailableError(RuntimeError):
    pass


def _api_key(api_key: str | None) -> str:
    key = api_key or os.environ.get("ALPHAVANTAGE_API_KEY")
    if not key:
        raise AlphaVantageUnavailableError(
            "No hay API key de Alpha Vantage configurada. Consigue una gratis en "
            "https://www.alphavantage.co/support/#api-key y pásala con --av-key o la "
            "variable de entorno ALPHAVANTAGE_API_KEY."
        )
    return key


def get_news_sentiment(
    symbol: str,
    limit: int = 50,
    time_from: str | None = None,
    api_key: str | None = None,
) -> list[dict]:
    """Recent news articles tagged with sentiment, mentioning `symbol`.

    Each entry has "title", "time_published" (e.g. "20260729T130000"),
    "source", "overall_sentiment_score", "overall_sentiment_label", and
    "ticker_sentiment" (a list with a per-symbol relevance/sentiment
    breakdown — a symbol can appear in an article without being its main
    subject, hence the relevance score).
    """
    params = {"function": "NEWS_SENTIMENT", "tickers": symbol, "limit": limit, "apikey": _api_key(api_key)}
    if time_from:
        params["time_from"] = time_from

    try:
        response = requests.get(_BASE_URL, params=params, timeout=_TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise AlphaVantageUnavailableError(f"No se pudo conectar con Alpha Vantage: {exc}") from exc

    if response.status_code != 200:
        raise AlphaVantageUnavailableError(f"Alpha Vantage respondió {response.status_code}: {response.text[:200]}")

    data = response.json()
    if isinstance(data, dict) and "feed" in data:
        return data["feed"]

    # Alpha Vantage returns HTTP 200 even for rate limits / bad keys, with the
    # explanation in one of these fields instead of a "feed" list.
    message = None
    if isinstance(data, dict):
        message = data.get("Note") or data.get("Information") or data.get("Error Message")
    raise AlphaVantageUnavailableError(message or f"Respuesta inesperada de Alpha Vantage para '{symbol}'.")
