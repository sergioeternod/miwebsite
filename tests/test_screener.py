import app.screener as screener_module
from app.screener import WINDOWS, _windowed_returns, screen_real_symbols, screen_synthetic


def test_windowed_returns_none_when_insufficient_history(uptrend_df):
    returns = _windowed_returns(uptrend_df)
    assert returns["semana"] is not None
    assert returns["mes"] is not None
    assert returns["año"] is None


def test_windowed_returns_all_present_with_enough_history(random_walk_df):
    returns = _windowed_returns(random_walk_df)
    for label in WINDOWS:
        assert returns[label] is not None


def test_windowed_returns_matches_manual_calc(uptrend_df):
    returns = _windowed_returns(uptrend_df)
    close = uptrend_df["Close"]
    expected_week = round((close.iloc[-1] / close.iloc[-6] - 1) * 100, 2)
    assert returns["semana"] == expected_week


def test_screen_synthetic_end_to_end():
    report = screen_synthetic()
    assert set(report["windows"]) == set(WINDOWS)
    assert len(report["returns_by_symbol"]) == 5
    assert not report["errors"]
    for label in WINDOWS:
        top = report["top_by_window"][label]
        assert len(top) <= 5
        returns = [r["return_pct"] for r in top]
        assert returns == sorted(returns, reverse=True)


def test_screen_synthetic_top_n_limits_results():
    report = screen_synthetic(top_n=2)
    for label in WINDOWS:
        assert len(report["top_by_window"][label]) <= 2


def test_screen_real_symbols_records_per_symbol_failures_without_crashing(monkeypatch, random_walk_df):
    def fake_get_ohlcv(symbol, period="2y", interval="1d"):
        if symbol == "BROKEN":
            raise RuntimeError("network unreachable")
        return random_walk_df

    monkeypatch.setattr(screener_module, "get_ohlcv", fake_get_ohlcv)
    report = screen_real_symbols(["OK", "BROKEN"])

    assert "OK" in report["returns_by_symbol"]
    assert "BROKEN" in report["errors"]
    assert "network unreachable" in report["errors"]["BROKEN"]
