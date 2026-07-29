import pytest
import requests

from app.data.finnhub_client import (
    FinnhubUnavailableError,
    get_earnings_calendar,
    get_earnings_surprises,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or str(payload)

    def json(self):
        return self._payload


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    with pytest.raises(FinnhubUnavailableError):
        get_earnings_surprises("AAPL")


def test_get_earnings_surprises_parses_response(monkeypatch):
    payload = [
        {"symbol": "AAPL", "period": "2024-06-30", "actual": 1.4, "estimate": 1.35, "surprise": 0.05, "surprisePercent": 3.7},
    ]
    monkeypatch.setattr(
        "app.data.finnhub_client.requests.get", lambda *a, **k: FakeResponse(200, payload)
    )
    result = get_earnings_surprises("AAPL", api_key="fake-key")
    assert result == payload


def test_get_earnings_calendar_parses_response(monkeypatch):
    payload = {"earningsCalendar": [{"symbol": "AAPL", "date": "2026-08-01"}]}
    monkeypatch.setattr(
        "app.data.finnhub_client.requests.get", lambda *a, **k: FakeResponse(200, payload)
    )
    result = get_earnings_calendar("AAPL", "2026-07-01", "2026-08-15", api_key="fake-key")
    assert result == payload["earningsCalendar"]


def test_non_200_response_raises(monkeypatch):
    monkeypatch.setattr(
        "app.data.finnhub_client.requests.get", lambda *a, **k: FakeResponse(403, text="Forbidden")
    )
    with pytest.raises(FinnhubUnavailableError):
        get_earnings_surprises("AAPL", api_key="fake-key")


def test_unexpected_payload_shape_raises(monkeypatch):
    monkeypatch.setattr(
        "app.data.finnhub_client.requests.get", lambda *a, **k: FakeResponse(200, {"unexpected": True})
    )
    with pytest.raises(FinnhubUnavailableError):
        get_earnings_surprises("AAPL", api_key="fake-key")


def test_network_error_raises(monkeypatch):
    def raise_connection_error(*args, **kwargs):
        raise requests.ConnectionError("blocked by proxy")

    monkeypatch.setattr("app.data.finnhub_client.requests.get", raise_connection_error)
    with pytest.raises(FinnhubUnavailableError):
        get_earnings_surprises("AAPL", api_key="fake-key")
