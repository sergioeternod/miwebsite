import pandas as pd
import pytest

from app.data.providers import DataUnavailableError, get_ohlcv
from app.data.stooq_client import StooqUnavailableError


def _fake_df():
    idx = pd.date_range("2024-01-01", periods=5, freq="D")
    return pd.DataFrame(
        {"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 100},
        index=idx,
    )


def test_get_ohlcv_uses_yahoo_when_it_succeeds(monkeypatch):
    monkeypatch.setattr("app.data.providers._get_ohlcv_yahoo", lambda *a, **k: _fake_df())

    def fail_stooq(*a, **k):
        raise AssertionError("stooq should not be called when Yahoo succeeds")

    monkeypatch.setattr("app.data.providers.stooq_client.get_ohlcv", fail_stooq)

    df = get_ohlcv("AAPL")
    assert len(df) == 5


def test_get_ohlcv_falls_back_to_stooq_when_yahoo_fails(monkeypatch):
    def fail_yahoo(*a, **k):
        raise DataUnavailableError("yahoo down")

    monkeypatch.setattr("app.data.providers._get_ohlcv_yahoo", fail_yahoo)
    monkeypatch.setattr("app.data.providers.stooq_client.get_ohlcv", lambda *a, **k: _fake_df())

    df = get_ohlcv("AAPL")
    assert len(df) == 5


def test_get_ohlcv_raises_with_both_errors_when_both_fail(monkeypatch):
    def fail_yahoo(*a, **k):
        raise DataUnavailableError("yahoo down")

    def fail_stooq(*a, **k):
        raise StooqUnavailableError("stooq down")

    monkeypatch.setattr("app.data.providers._get_ohlcv_yahoo", fail_yahoo)
    monkeypatch.setattr("app.data.providers.stooq_client.get_ohlcv", fail_stooq)

    with pytest.raises(DataUnavailableError, match="yahoo down") as exc_info:
        get_ohlcv("AAPL")
    assert "stooq down" in str(exc_info.value)
