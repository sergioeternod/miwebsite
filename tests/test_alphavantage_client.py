import pytest
import requests

from app.data.alphavantage_client import AlphaVantageUnavailableError, get_news_sentiment


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or str(payload)

    def json(self):
        return self._payload


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    with pytest.raises(AlphaVantageUnavailableError):
        get_news_sentiment("AAPL")


def test_get_news_sentiment_parses_feed(monkeypatch):
    payload = {
        "items": "1",
        "feed": [
            {
                "title": "Apple beats on iPhone sales",
                "time_published": "20260729T130000",
                "source": "Reuters",
                "overall_sentiment_score": 0.3,
                "overall_sentiment_label": "Somewhat-Bullish",
                "ticker_sentiment": [
                    {"ticker": "AAPL", "relevance_score": "0.9", "ticker_sentiment_score": "0.3", "ticker_sentiment_label": "Somewhat-Bullish"}
                ],
            }
        ],
    }
    monkeypatch.setattr("app.data.alphavantage_client.requests.get", lambda *a, **k: FakeResponse(200, payload))
    result = get_news_sentiment("AAPL", api_key="fake-key")
    assert result == payload["feed"]


def test_non_200_response_raises(monkeypatch):
    monkeypatch.setattr("app.data.alphavantage_client.requests.get", lambda *a, **k: FakeResponse(403, text="Forbidden"))
    with pytest.raises(AlphaVantageUnavailableError):
        get_news_sentiment("AAPL", api_key="fake-key")


def test_rate_limit_note_raises_with_message(monkeypatch):
    payload = {"Information": "Thank you for using Alpha Vantage! Our standard API rate limit is 25 requests per day."}
    monkeypatch.setattr("app.data.alphavantage_client.requests.get", lambda *a, **k: FakeResponse(200, payload))
    with pytest.raises(AlphaVantageUnavailableError, match="rate limit"):
        get_news_sentiment("AAPL", api_key="fake-key")


def test_invalid_key_error_message_raises(monkeypatch):
    payload = {"Error Message": "the parameter apikey is invalid"}
    monkeypatch.setattr("app.data.alphavantage_client.requests.get", lambda *a, **k: FakeResponse(200, payload))
    with pytest.raises(AlphaVantageUnavailableError, match="apikey"):
        get_news_sentiment("AAPL", api_key="fake-key")


def test_network_error_raises(monkeypatch):
    def raise_connection_error(*args, **kwargs):
        raise requests.ConnectionError("blocked by proxy")

    monkeypatch.setattr("app.data.alphavantage_client.requests.get", raise_connection_error)
    with pytest.raises(AlphaVantageUnavailableError):
        get_news_sentiment("AAPL", api_key="fake-key")
