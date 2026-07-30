import numpy as np
import pandas as pd
import pytest

import app.portfolio as portfolio_module
from app.portfolio import (
    _combine_equity_curves,
    _find_start_index,
    _select_portfolio,
    _walk_forward_result,
    simulate_portfolio_real,
    simulate_portfolio_synthetic,
)


def _make_ohlcv(close: pd.Series, start_date: str = "2023-01-01") -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "Open": close.shift(1).fillna(close.iloc[0]),
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": 1000,
        }
    )
    df.index = pd.date_range(start_date, periods=len(df), freq="D")
    df.index.name = "Date"
    return df


@pytest.fixture
def long_uptrend_df():
    close = pd.Series(np.linspace(100, 300, 400))
    return _make_ohlcv(close)


def test_find_start_index_matches_exact_date(long_uptrend_df):
    idx = _find_start_index(long_uptrend_df, "2023-06-01")
    assert long_uptrend_df.index[idx] == pd.Timestamp("2023-06-01")


def test_find_start_index_before_data_returns_zero(long_uptrend_df):
    assert _find_start_index(long_uptrend_df, "2020-01-01") == 0


def test_find_start_index_after_data_returns_length(long_uptrend_df):
    assert _find_start_index(long_uptrend_df, "2030-01-01") == len(long_uptrend_df)


def test_select_portfolio_ranks_by_confidence_desc(monkeypatch, long_uptrend_df):
    fake_confidences = {"A": 60.0, "B": 90.0, "C": 75.0}

    def fake_recommend(window, symbol="", initial_capital=10000.0, commission_bps=5.0, allow_short=True):
        return {"overall_action": "BUY", "confidence_pct": fake_confidences[symbol]}

    monkeypatch.setattr(portfolio_module, "recommend", fake_recommend)
    dfs = {s: long_uptrend_df for s in fake_confidences}
    start_idx_by_symbol = {s: 200 for s in fake_confidences}

    portfolio = _select_portfolio(dfs, start_idx_by_symbol, portfolio_size=2, allow_short=True, initial_capital=10000.0, commission_bps=5.0)

    assert [p["symbol"] for p in portfolio] == ["B", "C"]


def test_select_portfolio_excludes_sell_when_shorts_disallowed(monkeypatch, long_uptrend_df):
    def fake_recommend(window, symbol="", initial_capital=10000.0, commission_bps=5.0, allow_short=True):
        return {"overall_action": "SELL" if symbol == "BEARISH" else "BUY", "confidence_pct": 80.0}

    monkeypatch.setattr(portfolio_module, "recommend", fake_recommend)
    dfs = {"BEARISH": long_uptrend_df, "BULLISH": long_uptrend_df}
    start_idx_by_symbol = {"BEARISH": 200, "BULLISH": 200}

    portfolio = _select_portfolio(dfs, start_idx_by_symbol, portfolio_size=5, allow_short=False, initial_capital=10000.0, commission_bps=5.0)

    assert [p["symbol"] for p in portfolio] == ["BULLISH"]


def test_select_portfolio_skips_symbols_below_min_warmup(monkeypatch, long_uptrend_df):
    monkeypatch.setattr(portfolio_module, "recommend", lambda *a, **k: {"overall_action": "BUY", "confidence_pct": 80.0})
    dfs = {"TOO_EARLY": long_uptrend_df}
    portfolio = _select_portfolio(dfs, {"TOO_EARLY": 10}, portfolio_size=5, allow_short=True, initial_capital=10000.0, commission_bps=5.0)
    assert portfolio == []


def test_walk_forward_result_always_buy_matches_buy_and_hold(monkeypatch, long_uptrend_df):
    monkeypatch.setattr(portfolio_module, "recommend", lambda *a, **k: {"overall_action": "BUY", "confidence_pct": 80.0})
    start_idx = 200
    capital = 10_000.0

    result = _walk_forward_result(long_uptrend_df, start_idx, "SYM", allow_short=True, capital=capital, commission_bps=0.0, step=1)

    close = long_uptrend_df["Close"]
    expected_final = capital * (close.iloc[-1] / close.iloc[start_idx])
    assert result["equity_curve"].iloc[-1] == pytest.approx(expected_final, rel=1e-6)


def test_walk_forward_result_pnl_amounts_reconcile_with_equity_curve(monkeypatch, long_uptrend_df):
    calls = {"n": 0}

    def alternating_recommend(window, symbol="", initial_capital=10000.0, commission_bps=5.0, allow_short=True):
        calls["n"] += 1
        return {"overall_action": "BUY" if calls["n"] % 2 == 0 else "SELL", "confidence_pct": 70.0}

    monkeypatch.setattr(portfolio_module, "recommend", alternating_recommend)
    result = _walk_forward_result(long_uptrend_df, 200, "SYM", allow_short=True, capital=10_000.0, commission_bps=5.0, step=5)

    total_trade_pnl = sum(t["pnl_amount"] for t in result["trades"])
    equity_change = result["equity_curve"].iloc[-1] - 10_000.0
    assert total_trade_pnl == pytest.approx(equity_change, abs=0.5)


def test_combine_equity_curves_sums_aligned_series():
    idx = pd.date_range("2026-01-01", periods=5, freq="D")
    r1 = {"equity_curve": pd.Series([100, 110, 120, 130, 140], index=idx)}
    r2 = {"equity_curve": pd.Series([200, 190, 180, 170, 160], index=idx)}
    combined = _combine_equity_curves([r1, r2], capital_per_symbol=100.0)
    assert combined.tolist() == [300, 300, 300, 300, 300]


def test_simulate_portfolio_synthetic_end_to_end_small(monkeypatch):
    # Keep this fast: mock recommend() so no real strategy backtests run.
    monkeypatch.setattr(portfolio_module, "recommend", lambda *a, **k: {"overall_action": "BUY", "confidence_pct": 80.0})
    report = simulate_portfolio_synthetic(portfolio_size=2, step=30)

    assert report["start_date"] == "2026-01-01"
    assert len(report["portfolio"]) == 2
    assert report["capital_per_symbol"] == pytest.approx(report["initial_capital"] / 2)
    per_symbol_sum = round(sum(p["final_equity"] for p in report["per_symbol"]), 2)
    assert per_symbol_sum == pytest.approx(report["final_equity"], abs=0.05)
    assert not report["errors"]


def test_simulate_portfolio_raises_when_no_candidates(monkeypatch):
    monkeypatch.setattr(portfolio_module, "recommend", lambda *a, **k: {"overall_action": "HOLD", "confidence_pct": 50.0})
    with pytest.raises(ValueError):
        simulate_portfolio_synthetic(portfolio_size=2, step=30)


def test_simulate_portfolio_real_records_per_symbol_fetch_failures(monkeypatch, long_uptrend_df):
    monkeypatch.setattr(portfolio_module, "recommend", lambda *a, **k: {"overall_action": "BUY", "confidence_pct": 80.0})

    def fake_get_ohlcv(symbol, period="3y", interval="1d"):
        if symbol == "BROKEN":
            raise RuntimeError("network unreachable")
        return long_uptrend_df

    monkeypatch.setattr(portfolio_module, "get_ohlcv", fake_get_ohlcv)
    report = simulate_portfolio_real(start_date="2023-06-01", symbols=["OK", "BROKEN"], portfolio_size=2, step=30)

    assert "BROKEN" in report["errors"]
    assert report["portfolio"] == [{"symbol": "OK", "action_at_selection": "BUY", "confidence_pct_at_selection": 80.0}]


def test_walk_forward_recommend_never_sees_future_data(monkeypatch, long_uptrend_df):
    """Regression guard: each recommend() call during the walk must only see
    rows up to and including the current day — never later ones."""
    seen_lengths = []

    def spy_recommend(window, symbol="", initial_capital=10000.0, commission_bps=5.0, allow_short=True):
        seen_lengths.append(len(window))
        return {"overall_action": "HOLD", "confidence_pct": 50.0}

    monkeypatch.setattr(portfolio_module, "recommend", spy_recommend)
    start_idx = 200
    _walk_forward_result(long_uptrend_df, start_idx, "SYM", allow_short=True, capital=10_000.0, commission_bps=5.0, step=50)

    assert seen_lengths == [start_idx + 1 + i for i in range(0, len(long_uptrend_df) - start_idx, 50)]


def test_walk_forward_result_ignores_low_confidence_flips(monkeypatch, long_uptrend_df):
    """A BUY/SELL call below min_confidence_pct must be treated like a HOLD
    (stay flat) — this is what stops a noisy/weak signal from flipping the
    position and racking up commission on trades that shouldn't have
    happened."""
    calls = {"n": 0}

    def alternating_low_confidence(window, symbol="", initial_capital=10000.0, commission_bps=5.0, allow_short=True):
        calls["n"] += 1
        return {"overall_action": "BUY" if calls["n"] % 2 == 0 else "SELL", "confidence_pct": 40.0}

    monkeypatch.setattr(portfolio_module, "recommend", alternating_low_confidence)
    result = _walk_forward_result(
        long_uptrend_df, 200, "SYM", allow_short=True, capital=10_000.0, commission_bps=5.0, step=5, min_confidence_pct=55.0
    )

    assert result["trades"] == []
    assert result["equity_curve"].iloc[-1] == pytest.approx(10_000.0)


def test_walk_forward_result_acts_when_confidence_meets_lowered_threshold(monkeypatch, long_uptrend_df):
    monkeypatch.setattr(portfolio_module, "recommend", lambda *a, **k: {"overall_action": "BUY", "confidence_pct": 40.0})
    result = _walk_forward_result(
        long_uptrend_df, 200, "SYM", allow_short=True, capital=10_000.0, commission_bps=0.0, step=1, min_confidence_pct=10.0
    )
    close = long_uptrend_df["Close"]
    expected_final = 10_000.0 * (close.iloc[-1] / close.iloc[200])
    assert result["equity_curve"].iloc[-1] == pytest.approx(expected_final, rel=1e-6)


def test_select_portfolio_excludes_candidates_below_min_confidence(monkeypatch, long_uptrend_df):
    def fake_recommend(window, symbol="", initial_capital=10000.0, commission_bps=5.0, allow_short=True):
        return {"overall_action": "BUY", "confidence_pct": 30.0 if symbol == "WEAK" else 80.0}

    monkeypatch.setattr(portfolio_module, "recommend", fake_recommend)
    dfs = {"WEAK": long_uptrend_df, "STRONG": long_uptrend_df}
    start_idx_by_symbol = {"WEAK": 200, "STRONG": 200}

    portfolio = _select_portfolio(
        dfs, start_idx_by_symbol, portfolio_size=5, allow_short=True, initial_capital=10000.0, commission_bps=5.0, min_confidence_pct=55.0
    )

    assert [p["symbol"] for p in portfolio] == ["STRONG"]


def test_simulate_portfolio_synthetic_min_confidence_pct_reduces_or_matches_trade_count(monkeypatch):
    """A stricter (higher) confidence bar should never cause *more* trades
    than a looser one, all else equal — it can only skip flips, not add them."""
    calls = {"n": 0}

    def noisy_recommend(window, symbol="", initial_capital=10000.0, commission_bps=5.0, allow_short=True):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"overall_action": "BUY", "confidence_pct": 95.0}  # portfolio-selection call always succeeds
        action = ["BUY", "SELL", "HOLD"][calls["n"] % 3]
        confidence = [45.0, 65.0, 85.0][calls["n"] % 3]
        return {"overall_action": action, "confidence_pct": confidence}

    monkeypatch.setattr(portfolio_module, "recommend", noisy_recommend)

    strict = simulate_portfolio_synthetic(portfolio_size=1, step=10, min_confidence_pct=90.0)
    calls["n"] = 0  # reset so the second run's first call is also the guaranteed-success selection call
    loose = simulate_portfolio_synthetic(portfolio_size=1, step=10, min_confidence_pct=0.0)

    strict_trades = strict["per_symbol"][0]["metrics"]["num_trades"]
    loose_trades = loose["per_symbol"][0]["metrics"]["num_trades"]
    assert strict_trades <= loose_trades
