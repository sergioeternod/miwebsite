import pandas as pd
import pytest

from app.data.stooq_client import StooqUnavailableError, get_ohlcv, to_stooq_symbol


class FakeResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


def _csv(dates, closes):
    lines = ["Date,Open,High,Low,Close,Volume"]
    for d, c in zip(dates, closes):
        lines.append(f"{d},{c},{c},{c},{c},1000")
    return "\n".join(lines)


def test_to_stooq_symbol_stock():
    assert to_stooq_symbol("AAPL") == "aapl.us"


def test_to_stooq_symbol_forex():
    assert to_stooq_symbol("EURUSD=X") == "eurusd"


def test_to_stooq_symbol_futures():
    assert to_stooq_symbol("GC=F") == "gc.f"


def test_to_stooq_symbol_crypto():
    assert to_stooq_symbol("BTC-USD") == "btcusd"


def test_to_stooq_symbol_index_override():
    assert to_stooq_symbol("^GSPC") == "^spx"
    assert to_stooq_symbol("^IXIC") == "^ndq"
    assert to_stooq_symbol("^DJI") == "^dji"


def test_get_ohlcv_parses_csv(monkeypatch):
    dates = pd.date_range("2024-01-01", periods=10, freq="D")
    csv_text = _csv([d.date() for d in dates], range(100, 110))
    monkeypatch.setattr("app.data.stooq_client.requests.get", lambda *a, **k: FakeResponse(200, csv_text))

    df = get_ohlcv("AAPL", period="max")
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert len(df) == 10
    assert df["Close"].iloc[0] == 100


def test_get_ohlcv_applies_period_cutoff(monkeypatch):
    dates = pd.date_range("2020-01-01", periods=2000, freq="D")
    csv_text = _csv([d.date() for d in dates], range(2000))
    monkeypatch.setattr("app.data.stooq_client.requests.get", lambda *a, **k: FakeResponse(200, csv_text))

    df = get_ohlcv("AAPL", period="1y")
    span_days = (df.index.max() - df.index.min()).days
    assert span_days <= 366
    assert df.index.max() == dates.max()


def test_get_ohlcv_applies_start_end(monkeypatch):
    dates = pd.date_range("2020-01-01", periods=100, freq="D")
    csv_text = _csv([d.date() for d in dates], range(100))
    monkeypatch.setattr("app.data.stooq_client.requests.get", lambda *a, **k: FakeResponse(200, csv_text))

    df = get_ohlcv("AAPL", start="2020-02-01", end="2020-02-10")
    assert df.index.min() == pd.Timestamp("2020-02-01")
    assert df.index.max() == pd.Timestamp("2020-02-10")


def test_get_ohlcv_raises_on_no_data_response(monkeypatch):
    monkeypatch.setattr("app.data.stooq_client.requests.get", lambda *a, **k: FakeResponse(200, "No data"))
    with pytest.raises(StooqUnavailableError):
        get_ohlcv("NOTREAL")


def test_get_ohlcv_raises_on_non_200(monkeypatch):
    monkeypatch.setattr("app.data.stooq_client.requests.get", lambda *a, **k: FakeResponse(403, ""))
    with pytest.raises(StooqUnavailableError):
        get_ohlcv("AAPL")


def test_get_ohlcv_raises_on_unsupported_interval(monkeypatch):
    with pytest.raises(StooqUnavailableError):
        get_ohlcv("AAPL", interval="1h")


def test_get_ohlcv_raises_on_connection_error(monkeypatch):
    import requests

    def raise_connection_error(*a, **k):
        raise requests.RequestException("boom")

    monkeypatch.setattr("app.data.stooq_client.requests.get", raise_connection_error)
    with pytest.raises(StooqUnavailableError):
        get_ohlcv("AAPL")
