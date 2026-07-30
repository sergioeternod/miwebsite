import pytest

from app.data.yahoo_client import YahooUnavailableError, get_ohlcv


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def _chart_payload(timestamps, close, adjclose=None, gmtoffset=-14400, error=None):
    if error:
        return {"chart": {"result": None, "error": error}}
    quote = {
        "open": [None if c is None else c - 0.5 for c in close],
        "high": [None if c is None else c + 1.0 for c in close],
        "low": [None if c is None else c - 1.0 for c in close],
        "close": close,
        "volume": [None if c is None else 1000 for c in close],
    }
    indicators = {"quote": [quote]}
    if adjclose is not None:
        indicators["adjclose"] = [{"adjclose": adjclose}]
    return {
        "chart": {
            "result": [
                {
                    "meta": {"gmtoffset": gmtoffset},
                    "timestamp": timestamps,
                    "indicators": indicators,
                }
            ],
            "error": None,
        }
    }


def test_get_ohlcv_parses_basic_response(monkeypatch):
    timestamps = [1690000000 + i * 86400 for i in range(5)]
    close = [100.0, 101.0, 102.0, 103.0, 104.0]
    payload = _chart_payload(timestamps, close)
    monkeypatch.setattr("app.data.yahoo_client.requests.get", lambda *a, **k: FakeResponse(200, payload))

    df = get_ohlcv("AAPL", period="1mo")
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert len(df) == 5
    assert df["Close"].iloc[0] == 100.0


def test_get_ohlcv_applies_adjclose_ratio_to_ohlc(monkeypatch):
    # A 2:1 split: raw close doubles overnight, adjclose reflects the
    # split-adjusted (halved) series instead.
    timestamps = [1690000000, 1690086400]
    close = [200.0, 100.0]
    adjclose = [100.0, 100.0]
    payload = _chart_payload(timestamps, close, adjclose=adjclose)
    monkeypatch.setattr("app.data.yahoo_client.requests.get", lambda *a, **k: FakeResponse(200, payload))

    df = get_ohlcv("NVDA", period="1mo")
    assert df["Close"].tolist() == [100.0, 100.0]
    # Open/High/Low for the first (pre-split) bar get scaled by the same
    # 100/200 = 0.5 ratio, so they end up roughly half their raw value too.
    assert df["Open"].iloc[0] == pytest.approx((200.0 - 0.5) * 0.5)


def test_get_ohlcv_dedupes_same_day_bars_keeping_the_last(monkeypatch):
    # Two bars on the same UTC calendar day (e.g. a regular daily close plus
    # a still-forming "live" bar for a near-24h instrument like forex/crypto)
    # must collapse to one row instead of raising on a duplicate date index.
    timestamps = [1704067200, 1704110400, 1704153600]  # 2024-01-01 00:00, 2024-01-01 12:00, 2024-01-02 00:00
    close = [100.0, 105.0, 110.0]
    payload = _chart_payload(timestamps, close, gmtoffset=0)
    monkeypatch.setattr("app.data.yahoo_client.requests.get", lambda *a, **k: FakeResponse(200, payload))

    df = get_ohlcv("EURUSD=X", period="1mo")
    assert len(df) == 2
    assert not df.index.duplicated().any()
    assert df["Close"].iloc[0] == 105.0  # the later same-day bar wins


def test_get_ohlcv_drops_bars_with_missing_close(monkeypatch):
    timestamps = [1690000000 + i * 86400 for i in range(3)]
    close = [100.0, None, 102.0]
    payload = _chart_payload(timestamps, close)
    monkeypatch.setattr("app.data.yahoo_client.requests.get", lambda *a, **k: FakeResponse(200, payload))

    df = get_ohlcv("AAPL", period="1mo")
    assert len(df) == 2


def test_get_ohlcv_raises_on_chart_error(monkeypatch):
    payload = {"chart": {"result": None, "error": {"code": "Not Found", "description": "No data found"}}}
    monkeypatch.setattr("app.data.yahoo_client.requests.get", lambda *a, **k: FakeResponse(200, payload))
    with pytest.raises(YahooUnavailableError, match="No data found"):
        get_ohlcv("NOTREAL")


def test_get_ohlcv_raises_on_non_200(monkeypatch):
    monkeypatch.setattr("app.data.yahoo_client.requests.get", lambda *a, **k: FakeResponse(403, {}))
    with pytest.raises(YahooUnavailableError):
        get_ohlcv("AAPL")


def test_get_ohlcv_raises_on_empty_result(monkeypatch):
    payload = {"chart": {"result": [], "error": None}}
    monkeypatch.setattr("app.data.yahoo_client.requests.get", lambda *a, **k: FakeResponse(200, payload))
    with pytest.raises(YahooUnavailableError):
        get_ohlcv("AAPL")


def test_get_ohlcv_raises_on_connection_error(monkeypatch):
    import requests

    def raise_connection_error(*a, **k):
        raise requests.RequestException("boom")

    monkeypatch.setattr("app.data.yahoo_client.requests.get", raise_connection_error)
    with pytest.raises(YahooUnavailableError):
        get_ohlcv("AAPL")


def test_get_ohlcv_uses_start_end_params(monkeypatch):
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured.update(params)
        timestamps = [1690000000, 1690086400]
        return FakeResponse(200, _chart_payload(timestamps, [100.0, 101.0]))

    monkeypatch.setattr("app.data.yahoo_client.requests.get", fake_get)
    get_ohlcv("AAPL", start="2023-01-01", end="2023-01-05")
    assert "period1" in captured and "period2" in captured
    assert "range" not in captured


def test_get_ohlcv_maps_valid_range_shorthand(monkeypatch):
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured.update(params)
        timestamps = [1690000000, 1690086400]
        return FakeResponse(200, _chart_payload(timestamps, [100.0, 101.0]))

    monkeypatch.setattr("app.data.yahoo_client.requests.get", fake_get)
    get_ohlcv("AAPL", period="2y")
    assert captured.get("range") == "2y"


def test_get_ohlcv_computes_window_for_nonstandard_period(monkeypatch):
    captured = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        captured.update(params)
        timestamps = [1690000000, 1690086400]
        return FakeResponse(200, _chart_payload(timestamps, [100.0, 101.0]))

    monkeypatch.setattr("app.data.yahoo_client.requests.get", fake_get)
    get_ohlcv("AAPL", period="13y")
    assert "range" not in captured
    assert "period1" in captured and "period2" in captured
