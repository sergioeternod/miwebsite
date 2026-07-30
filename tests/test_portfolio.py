import numpy as np
import pandas as pd
import pytest

import app.portfolio as portfolio_module
from app.portfolio import (
    ADAPTIVE_REGRET_MAX_BOOST,
    DEFAULT_STOP_LOSS_PCT,
    _closed_trades_so_far,
    _combine_equity_curves,
    _find_start_index,
    _recent_regret_boost,
    _risk_multiplier,
    _risk_parity_weights,
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
    r1 = {"symbol": "A", "equity_curve": pd.Series([100, 110, 120, 130, 140], index=idx)}
    r2 = {"symbol": "B", "equity_curve": pd.Series([200, 190, 180, 170, 160], index=idx)}
    combined = _combine_equity_curves([r1, r2], capital_by_symbol={"A": 100.0, "B": 100.0})
    assert combined.tolist() == [300, 300, 300, 300, 300]


def test_combine_equity_curves_uses_each_symbols_own_capital():
    idx = pd.date_range("2026-01-01", periods=3, freq="D")
    short_idx = idx[1:]  # symbol B "starts" one day later than the combined date axis
    r1 = {"symbol": "A", "equity_curve": pd.Series([100, 110, 120], index=idx)}
    r2 = {"symbol": "B", "equity_curve": pd.Series([50, 55], index=short_idx)}
    combined = _combine_equity_curves([r1, r2], capital_by_symbol={"A": 100.0, "B": 50.0})
    # Day 1: A=100, B not started yet -> filled with B's own starting capital (50), not A's.
    assert combined.iloc[0] == 150


def test_simulate_portfolio_synthetic_end_to_end_small(monkeypatch):
    # Keep this fast: mock recommend() so no real strategy backtests run.
    monkeypatch.setattr(portfolio_module, "recommend", lambda *a, **k: {"overall_action": "BUY", "confidence_pct": 80.0})
    report = simulate_portfolio_synthetic(portfolio_size=2, step=30)

    assert report["start_date"] == "2026-01-01"
    assert len(report["portfolio"]) == 2
    assert set(report["capital_by_symbol"]) == {p["symbol"] for p in report["portfolio"]}
    assert sum(report["capital_by_symbol"].values()) == pytest.approx(report["initial_capital"])
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
    assert len(report["portfolio"]) == 1
    candidate = report["portfolio"][0]
    assert candidate["volatility_pct"] > 0
    del candidate["volatility_pct"]
    assert candidate == {
        "symbol": "OK",
        "action_at_selection": "BUY",
        "confidence_pct_at_selection": 80.0,
        "sharpe_ratio": None,
        "max_drawdown_pct": None,
        "risk_adjusted_score": 80.0,
    }


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


def _hindsight_trade(entry_price, exit_price, equity_at_entry=10_000.0):
    return {"direction": "long", "entry_price": entry_price, "exit_price": exit_price, "equity_at_entry": equity_at_entry}


def test_recent_regret_boost_is_zero_with_no_closed_trades():
    assert _recent_regret_boost([], commission_bps=0.0) == 0.0


def test_recent_regret_boost_positive_after_bad_calls():
    trades = [_hindsight_trade(100, 90), _hindsight_trade(100, 80)]
    assert _recent_regret_boost(trades, commission_bps=0.0) > 0.0


def test_recent_regret_boost_capped_at_max():
    trades = [_hindsight_trade(100, 1)] * 3
    assert _recent_regret_boost(trades, commission_bps=0.0) == ADAPTIVE_REGRET_MAX_BOOST


def test_recent_regret_boost_only_uses_last_lookback_trades():
    # ADAPTIVE_REGRET_LOOKBACK is 3: only the last 3 (all "good") should count,
    # regardless of how many bad calls came before them.
    bad = _hindsight_trade(100, 50)
    good = _hindsight_trade(100, 110)
    trades = [bad, bad, bad, bad, good, good, good]
    assert _recent_regret_boost(trades, commission_bps=0.0) == 0.0


def test_closed_trades_so_far_empty_when_t_not_after_start(long_uptrend_df):
    positions = [0] * len(long_uptrend_df)
    assert _closed_trades_so_far(long_uptrend_df, positions, 200, 200, commission_bps=0.0, capital=10_000.0) == []


def test_closed_trades_so_far_ignores_positions_at_and_after_t(long_uptrend_df):
    """Regression guard: the sub-slice used for the regret look-back must
    stop strictly before `t` — a value planted at index `t` (a "future" bar
    from the perspective of the decision being made) must never leak in."""
    positions = [0] * len(long_uptrend_df)
    positions[200] = 1
    positions[209] = 999  # sentinel: if this leaked in, it would show up as a bogus second trade
    trades = _closed_trades_so_far(long_uptrend_df, positions, 200, 209, commission_bps=0.0, capital=10_000.0)
    assert len(trades) == 1
    assert trades[0]["direction"] == "long"


def test_walk_forward_result_includes_hindsight_summary(monkeypatch, long_uptrend_df):
    calls = {"n": 0}

    def alternating_recommend(window, symbol="", initial_capital=10000.0, commission_bps=5.0, allow_short=True):
        calls["n"] += 1
        return {"overall_action": "BUY" if calls["n"] % 2 == 0 else "SELL", "confidence_pct": 70.0}

    monkeypatch.setattr(portfolio_module, "recommend", alternating_recommend)
    result = _walk_forward_result(long_uptrend_df, 200, "SYM", allow_short=True, capital=10_000.0, commission_bps=5.0, step=5)

    closed_trades = [t for t in result["trades"] if not t.get("open")]
    assert all(t.get("hindsight") is not None for t in closed_trades)
    assert result["hindsight_summary"]["num_trades"] == len(closed_trades)


def test_walk_forward_adaptive_learning_reduces_trades_after_bad_streak(monkeypatch, long_uptrend_df):
    """In a strong uptrend, alternating BUY/SELL calls right at the
    confidence bar keep losing money on the SELL leg. Adaptive learning
    should notice via hindsight and raise the bar enough to stop acting on
    it, ending up with fewer trades (and, in this scenario, a better
    result) than the same run with adaptive learning turned off — but the
    mechanism is judged here on trade count, not on promising better P&L in
    general."""
    calls = {"n": 0}

    def alternating_borderline(window, symbol="", initial_capital=10000.0, commission_bps=5.0, allow_short=True):
        calls["n"] += 1
        action = "SELL" if calls["n"] % 2 == 1 else "BUY"
        return {"overall_action": action, "confidence_pct": 55.5}

    monkeypatch.setattr(portfolio_module, "recommend", alternating_borderline)
    adaptive = _walk_forward_result(
        long_uptrend_df, 200, "SYM", allow_short=True, capital=10_000.0, commission_bps=5.0, step=5,
        min_confidence_pct=55.0, adaptive_learning=True,
    )

    calls["n"] = 0
    baseline = _walk_forward_result(
        long_uptrend_df, 200, "SYM", allow_short=True, capital=10_000.0, commission_bps=5.0, step=5,
        min_confidence_pct=55.0, adaptive_learning=False,
    )

    assert len(adaptive["trades"]) < len(baseline["trades"])


def test_walk_forward_adaptive_learning_never_uses_future_positions(monkeypatch, long_uptrend_df):
    """Regression guard: the regret look-back must only ever be computed
    from positions already decided strictly before the current decision
    point `t` — mirroring the no-lookahead discipline `recommend()` itself
    is held to."""
    real_closed_trades_so_far = portfolio_module._closed_trades_so_far
    seen_t_values = []

    def spy(df, positions, start_idx, t, commission_bps, capital):
        assert all(p == 0 for p in positions[t:])  # nothing beyond t has been decided yet
        seen_t_values.append(t)
        return real_closed_trades_so_far(df, positions, start_idx, t, commission_bps, capital)

    monkeypatch.setattr(portfolio_module, "_closed_trades_so_far", spy)
    monkeypatch.setattr(portfolio_module, "recommend", lambda *a, **k: {"overall_action": "BUY", "confidence_pct": 80.0})
    _walk_forward_result(long_uptrend_df, 200, "SYM", allow_short=True, capital=10_000.0, commission_bps=5.0, step=10)

    assert seen_t_values  # sanity: the adaptive path actually ran


def test_walk_forward_result_adaptive_learning_off_matches_fixed_threshold(monkeypatch, long_uptrend_df):
    """With adaptive_learning=False, the confidence bar must stay exactly
    at min_confidence_pct regardless of how bad recent trades looked in
    hindsight."""
    monkeypatch.setattr(portfolio_module, "recommend", lambda *a, **k: {"overall_action": "BUY", "confidence_pct": 40.0})
    result = _walk_forward_result(
        long_uptrend_df, 200, "SYM", allow_short=True, capital=10_000.0, commission_bps=0.0, step=1,
        min_confidence_pct=10.0, adaptive_learning=False,
    )
    close = long_uptrend_df["Close"]
    expected_final = 10_000.0 * (close.iloc[-1] / close.iloc[200])
    assert result["equity_curve"].iloc[-1] == pytest.approx(expected_final, rel=1e-6)


def test_simulate_portfolio_synthetic_includes_hindsight_summary(monkeypatch):
    monkeypatch.setattr(portfolio_module, "recommend", lambda *a, **k: {"overall_action": "BUY", "confidence_pct": 80.0})
    report = simulate_portfolio_synthetic(portfolio_size=2, step=30)

    assert "hindsight_summary" in report
    assert all("hindsight_summary" in p for p in report["per_symbol"])


def _fake_rec(action="BUY", confidence=80.0, sharpe_ratio=None, max_drawdown_pct=None):
    return {
        "overall_action": action,
        "confidence_pct": confidence,
        "best_historical_strategy": {
            "strategy": "fake_strategy",
            "avg_profit_per_trade_pct": 1.0,
            "sharpe_ratio": sharpe_ratio,
            "max_drawdown_pct": max_drawdown_pct,
        },
    }


def test_risk_multiplier_neutral_with_missing_stats():
    assert _risk_multiplier(None, None) == 1.0
    assert _risk_multiplier(float("nan"), float("nan")) == 1.0


def test_risk_multiplier_rewards_good_sharpe_and_penalizes_bad():
    good = _risk_multiplier(sharpe_ratio=2.0, max_drawdown_pct=-5.0)
    bad = _risk_multiplier(sharpe_ratio=-1.0, max_drawdown_pct=-45.0)
    assert good > 1.0
    assert bad < 1.0
    assert good > bad


def test_risk_multiplier_stays_within_bounds():
    assert _risk_multiplier(sharpe_ratio=10.0, max_drawdown_pct=0.0) == pytest.approx(1.4)
    assert _risk_multiplier(sharpe_ratio=-10.0, max_drawdown_pct=-90.0) == pytest.approx(0.6 * 0.5)


def test_select_portfolio_ranks_by_risk_adjusted_score_not_raw_confidence(monkeypatch, long_uptrend_df):
    """A symbol with slightly lower confidence but a much better historical
    risk profile (Sharpe/drawdown) should be able to outrank one with higher
    raw confidence but a rough track record."""

    def fake_recommend(window, symbol="", initial_capital=10000.0, commission_bps=5.0, allow_short=True):
        if symbol == "LOUD_BUT_RISKY":
            return _fake_rec(confidence=80.0, sharpe_ratio=-1.0, max_drawdown_pct=-45.0)
        return _fake_rec(confidence=70.0, sharpe_ratio=2.0, max_drawdown_pct=-5.0)

    monkeypatch.setattr(portfolio_module, "recommend", fake_recommend)
    dfs = {"LOUD_BUT_RISKY": long_uptrend_df, "CALM_AND_CONSISTENT": long_uptrend_df}
    start_idx_by_symbol = {"LOUD_BUT_RISKY": 200, "CALM_AND_CONSISTENT": 200}

    portfolio = _select_portfolio(
        dfs, start_idx_by_symbol, portfolio_size=2, allow_short=True, initial_capital=10000.0, commission_bps=5.0
    )

    assert [c["symbol"] for c in portfolio] == ["CALM_AND_CONSISTENT", "LOUD_BUT_RISKY"]
    assert portfolio[0]["risk_adjusted_score"] > portfolio[1]["risk_adjusted_score"]


def test_select_portfolio_applies_earnings_overlay_when_enabled(monkeypatch, long_uptrend_df):
    monkeypatch.setattr(portfolio_module, "recommend", lambda *a, **k: _fake_rec(action="BUY", confidence=50.0))

    def fake_overlay(rec, symbol, **kwargs):
        boosted = dict(rec)
        boosted["confidence_pct"] = 90.0
        boosted["earnings"] = {"available": True, "signal": "bullish"}
        return boosted

    monkeypatch.setattr(portfolio_module, "apply_earnings_overlay", fake_overlay)
    portfolio = _select_portfolio(
        {"AAPL": long_uptrend_df}, {"AAPL": 200}, portfolio_size=1, allow_short=True,
        initial_capital=10000.0, commission_bps=5.0, min_confidence_pct=60.0, include_earnings=True,
    )
    # Raw confidence (50) is below the 60 threshold; only the overlay-boosted
    # confidence (90) clears it — proves the overlay runs before the filter.
    assert len(portfolio) == 1
    assert portfolio[0]["confidence_pct_at_selection"] == 90.0
    assert portfolio[0]["earnings"] == {"available": True, "signal": "bullish"}


def test_select_portfolio_applies_news_overlay_when_enabled(monkeypatch, long_uptrend_df):
    monkeypatch.setattr(portfolio_module, "recommend", lambda *a, **k: _fake_rec(action="BUY", confidence=80.0))

    def fake_overlay(rec, symbol, **kwargs):
        boosted = dict(rec)
        boosted["news"] = {"available": True, "signal": "bearish"}
        return boosted

    monkeypatch.setattr(portfolio_module, "apply_news_overlay", fake_overlay)
    portfolio = _select_portfolio(
        {"AAPL": long_uptrend_df}, {"AAPL": 200}, portfolio_size=1, allow_short=True,
        initial_capital=10000.0, commission_bps=5.0, include_news=True,
    )
    assert portfolio[0]["news"] == {"available": True, "signal": "bearish"}


def test_select_portfolio_omits_earnings_news_keys_by_default(monkeypatch, long_uptrend_df):
    monkeypatch.setattr(portfolio_module, "recommend", lambda *a, **k: _fake_rec(action="BUY", confidence=80.0))
    portfolio = _select_portfolio(
        {"AAPL": long_uptrend_df}, {"AAPL": 200}, portfolio_size=1, allow_short=True,
        initial_capital=10000.0, commission_bps=5.0,
    )
    assert "earnings" not in portfolio[0]
    assert "news" not in portfolio[0]


def test_simulate_portfolio_synthetic_earnings_overlay_never_reaches_walk_forward(monkeypatch):
    """Regression guard: include_earnings must only ever be consulted at
    portfolio selection (once per candidate symbol), never inside the daily
    walk-forward loop — calling Finnhub on every simulated day would both
    leak future earnings data into past decisions and blow through rate
    limits. Call count should match the number of symbols scanned at
    selection, not that number times the number of simulated days."""
    calls = {"n": 0}

    def counting_overlay(rec, symbol, **kwargs):
        calls["n"] += 1
        return rec

    monkeypatch.setattr(portfolio_module, "apply_earnings_overlay", counting_overlay)
    monkeypatch.setattr(portfolio_module, "recommend", lambda *a, **k: _fake_rec(action="BUY", confidence=80.0))

    simulate_portfolio_synthetic(portfolio_size=2, step=1, include_earnings=True)

    num_symbols_scanned = len(portfolio_module.DEFAULT_PORTFOLIO_PROFILES)
    assert calls["n"] == num_symbols_scanned


def test_simulate_portfolio_synthetic_adaptive_learning_flag_is_threaded(monkeypatch, long_uptrend_df):
    # `_run_simulation` calls `_walk_forward_result` positionally, with
    # `adaptive_learning` as the last argument — assert on that directly
    # instead of via kwargs.
    seen_flags = []
    real_walk_forward_result = portfolio_module._walk_forward_result

    def spy(*args, **kwargs):
        seen_flags.append(args[8] if len(args) > 8 else kwargs.get("adaptive_learning"))
        return real_walk_forward_result(*args, **kwargs)

    monkeypatch.setattr(portfolio_module, "_walk_forward_result", spy)
    monkeypatch.setattr(portfolio_module, "recommend", lambda *a, **k: {"overall_action": "BUY", "confidence_pct": 80.0})

    simulate_portfolio_synthetic(portfolio_size=1, step=30, adaptive_learning=False)

    assert seen_flags == [False]


# ---------------------------------------------------------------------------
# Asset-class diversification cap
# ---------------------------------------------------------------------------


def test_select_portfolio_caps_picks_per_asset_class(monkeypatch, long_uptrend_df):
    """Two crypto pairs shouldn't both make the cut when a cap of 1-per-class
    is in effect, even if both individually outscore everything else."""
    monkeypatch.setattr(
        portfolio_module,
        "recommend",
        lambda window, symbol="", **k: _fake_rec(
            action="SELL", confidence=95.0 if "USD" in symbol else 60.0, sharpe_ratio=1.0, max_drawdown_pct=-5.0
        ),
    )
    dfs = {"BTC-USD": long_uptrend_df, "ETH-USD": long_uptrend_df, "^GSPC": long_uptrend_df}
    start_idx_by_symbol = {s: 200 for s in dfs}

    portfolio = _select_portfolio(
        dfs, start_idx_by_symbol, portfolio_size=3, allow_short=True, initial_capital=10000.0,
        commission_bps=5.0, max_per_asset_class=1,
    )

    crypto_picks = [c for c in portfolio if c["symbol"] in ("BTC-USD", "ETH-USD")]
    assert len(crypto_picks) == 1
    assert "^GSPC" in [c["symbol"] for c in portfolio]


def test_select_portfolio_max_per_asset_class_none_disables_cap(monkeypatch, long_uptrend_df):
    monkeypatch.setattr(
        portfolio_module, "recommend", lambda window, symbol="", **k: _fake_rec(action="SELL", confidence=95.0)
    )
    dfs = {"BTC-USD": long_uptrend_df, "ETH-USD": long_uptrend_df}
    start_idx_by_symbol = {s: 200 for s in dfs}

    portfolio = _select_portfolio(
        dfs, start_idx_by_symbol, portfolio_size=2, allow_short=True, initial_capital=10000.0,
        commission_bps=5.0, max_per_asset_class=None,
    )
    assert len(portfolio) == 2


def test_select_portfolio_includes_volatility_pct(monkeypatch, long_uptrend_df):
    monkeypatch.setattr(portfolio_module, "recommend", lambda *a, **k: _fake_rec(action="BUY", confidence=80.0))
    portfolio = _select_portfolio(
        {"AAPL": long_uptrend_df}, {"AAPL": 200}, portfolio_size=1, allow_short=True,
        initial_capital=10000.0, commission_bps=5.0,
    )
    assert portfolio[0]["volatility_pct"] > 0


# ---------------------------------------------------------------------------
# Risk-parity position sizing
# ---------------------------------------------------------------------------


def test_risk_parity_weights_favor_lower_volatility():
    portfolio = [
        {"symbol": "CALM", "volatility_pct": 0.5},
        {"symbol": "WILD", "volatility_pct": 5.0},
    ]
    weights = _risk_parity_weights(portfolio)
    assert weights["CALM"] > weights["WILD"]
    assert weights["CALM"] + weights["WILD"] == pytest.approx(1.0)


def test_risk_parity_weights_equal_for_equal_volatility():
    portfolio = [{"symbol": "A", "volatility_pct": 1.0}, {"symbol": "B", "volatility_pct": 1.0}]
    weights = _risk_parity_weights(portfolio)
    assert weights["A"] == pytest.approx(weights["B"])


def test_risk_parity_weights_handles_missing_volatility():
    portfolio = [{"symbol": "A", "volatility_pct": None}, {"symbol": "B", "volatility_pct": 1.0}]
    weights = _risk_parity_weights(portfolio)
    assert weights["A"] + weights["B"] == pytest.approx(1.0)
    assert weights["A"] > 0 and weights["B"] > 0


def test_simulate_portfolio_synthetic_risk_parity_sizes_unequally(monkeypatch):
    """With two symbols of very different volatility, risk-parity sizing
    should NOT split capital 50/50 the way equal-weighting would."""
    calls = {"n": 0}

    def fake_recommend(window, symbol="", **k):
        calls["n"] += 1
        return _fake_rec(action="BUY", confidence=80.0)

    monkeypatch.setattr(portfolio_module, "recommend", fake_recommend)
    report = simulate_portfolio_synthetic(portfolio_size=2, step=30, risk_parity_sizing=True)
    capitals = list(report["capital_by_symbol"].values())
    assert sum(capitals) == pytest.approx(report["initial_capital"])
    # The two synthetic profiles picked have different historical volatility
    # (different regimes/seeds), so risk parity shouldn't land on an exact 50/50 split.
    assert capitals[0] != pytest.approx(capitals[1])


def test_simulate_portfolio_synthetic_equal_weight_when_disabled(monkeypatch):
    monkeypatch.setattr(portfolio_module, "recommend", lambda *a, **k: _fake_rec(action="BUY", confidence=80.0))
    report = simulate_portfolio_synthetic(portfolio_size=2, step=30, risk_parity_sizing=False)
    capitals = list(report["capital_by_symbol"].values())
    assert capitals[0] == pytest.approx(capitals[1])
    assert capitals[0] == pytest.approx(report["initial_capital"] / 2)


# ---------------------------------------------------------------------------
# Stop-loss
# ---------------------------------------------------------------------------


def test_stop_loss_triggered_for_long_position():
    from app.portfolio import _stop_loss_triggered

    assert _stop_loss_triggered(price_today=80.0, entry_price=100.0, direction=1, stop_loss_pct=15.0) is True
    assert _stop_loss_triggered(price_today=90.0, entry_price=100.0, direction=1, stop_loss_pct=15.0) is False


def test_stop_loss_triggered_for_short_position():
    from app.portfolio import _stop_loss_triggered

    # Short position: price RISING hurts it.
    assert _stop_loss_triggered(price_today=120.0, entry_price=100.0, direction=-1, stop_loss_pct=15.0) is True
    assert _stop_loss_triggered(price_today=105.0, entry_price=100.0, direction=-1, stop_loss_pct=15.0) is False


def test_walk_forward_result_stop_loss_flattens_a_crashing_long(monkeypatch):
    """A long position entered once (BUY on the very first bar, HOLD forever
    after — so only the stop-loss, never a fresh signal, can close it) then
    hit with a sharp, sustained drop should get flattened by the stop-loss,
    preserving capital that riding the full decline would have lost."""
    close = pd.Series([100.0] * 200 + [100 - i for i in range(1, 61)])  # flat, then a steady 60-point slide
    df = _make_ohlcv(close)

    def buy_once_then_hold(window, *a, **k):
        action = "BUY" if len(window) == 200 else "HOLD"
        return {"overall_action": action, "confidence_pct": 80.0}

    monkeypatch.setattr(portfolio_module, "recommend", buy_once_then_hold)

    with_stop = _walk_forward_result(
        df, 199, "SYM", allow_short=True, capital=10_000.0, commission_bps=0.0, step=1, stop_loss_pct=15.0
    )
    without_stop = _walk_forward_result(
        df, 199, "SYM", allow_short=True, capital=10_000.0, commission_bps=0.0, step=1, stop_loss_pct=None
    )

    assert with_stop["equity_curve"].iloc[-1] > without_stop["equity_curve"].iloc[-1]
    assert any(t.get("open") is not True for t in with_stop["trades"])  # the stop-loss closed the trade


def test_walk_forward_result_no_stop_loss_when_disabled(monkeypatch):
    close = pd.Series([100.0] * 200 + [100 - i for i in range(1, 61)])
    df = _make_ohlcv(close)
    monkeypatch.setattr(portfolio_module, "recommend", lambda *a, **k: {"overall_action": "BUY", "confidence_pct": 80.0})

    result = _walk_forward_result(
        df, 199, "SYM", allow_short=True, capital=10_000.0, commission_bps=0.0, step=1, stop_loss_pct=None
    )
    close_final = close.iloc[-1]
    expected_final = 10_000.0 * (close_final / close.iloc[199])
    assert result["equity_curve"].iloc[-1] == pytest.approx(expected_final, rel=1e-6)
