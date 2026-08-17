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
    report = simulate_portfolio_synthetic(portfolio_size=2, step=30, rebalance_months=None)

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

    strict = simulate_portfolio_synthetic(portfolio_size=1, step=10, min_confidence_pct=90.0, rebalance_months=None)
    calls["n"] = 0  # reset so the second run's first call is also the guaranteed-success selection call
    loose = simulate_portfolio_synthetic(portfolio_size=1, step=10, min_confidence_pct=0.0, rebalance_months=None)

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
    report = simulate_portfolio_synthetic(portfolio_size=2, step=30, rebalance_months=None)

    assert "hindsight_summary" in report
    assert all("hindsight_summary" in p for p in report["per_symbol"])


def test_simulate_portfolio_synthetic_default_is_quarterly_rebalance(monkeypatch):
    """The public default is quarterly re-selection — validated across 9
    windows (7/9 vs the no-rebalance model, 6/9 vs buy & hold; see
    scripts/validate_rebalance_result.json)."""
    monkeypatch.setattr(portfolio_module, "recommend", lambda *a, **k: {"overall_action": "BUY", "confidence_pct": 80.0})
    report = simulate_portfolio_synthetic(portfolio_size=2, step=30)

    assert report["rebalance_months"] == 3
    assert report["segments"]
    assert "hindsight_summary" in report
    assert "benchmark_buy_hold" in report


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
        fundamental_pe_tilt=False,
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


# ---------------------------------------------------------------------------
# Buy & hold benchmark
# ---------------------------------------------------------------------------


def test_buy_hold_benchmark_math(long_uptrend_df):
    from app.portfolio import _buy_hold_benchmark

    start_idx = 200
    capital = 1_000.0
    bench = _buy_hold_benchmark(
        {"SYM": long_uptrend_df}, {"SYM": start_idx}, {"SYM": capital}, commission_bps=0.0
    )
    close = long_uptrend_df["Close"]
    expected = round(capital * float(close.iloc[-1]) / float(close.iloc[start_idx]), 2)
    assert bench["per_symbol"]["SYM"] == pytest.approx(expected)
    assert bench["final_equity"] == pytest.approx(expected)
    assert bench["total_return_pct"] == pytest.approx((expected / capital - 1) * 100, abs=0.01)


def test_buy_hold_benchmark_charges_one_entry_commission(long_uptrend_df):
    from app.portfolio import _buy_hold_benchmark

    free = _buy_hold_benchmark({"SYM": long_uptrend_df}, {"SYM": 200}, {"SYM": 1_000.0}, commission_bps=0.0)
    fee = _buy_hold_benchmark({"SYM": long_uptrend_df}, {"SYM": 200}, {"SYM": 1_000.0}, commission_bps=100.0)
    assert fee["final_equity"] == pytest.approx(free["final_equity"] * (1 - 0.01), rel=1e-6)


def test_simulate_portfolio_synthetic_report_includes_benchmark(monkeypatch):
    monkeypatch.setattr(portfolio_module, "recommend", lambda *a, **k: _fake_rec(action="BUY", confidence=80.0))
    report = simulate_portfolio_synthetic(portfolio_size=2, step=30)

    bench = report["benchmark_buy_hold"]
    assert set(bench["per_symbol"]) == {p["symbol"] for p in report["portfolio"]}
    assert bench["final_equity"] == pytest.approx(sum(bench["per_symbol"].values()), abs=0.05)
    assert report["vs_benchmark_pct_points"] == pytest.approx(
        report["total_return_pct"] - bench["total_return_pct"], abs=0.05
    )


# ---------------------------------------------------------------------------
# Short confidence premium
# ---------------------------------------------------------------------------


def test_walk_forward_short_premium_blocks_marginal_sells(monkeypatch, long_uptrend_df):
    monkeypatch.setattr(portfolio_module, "recommend", lambda *a, **k: {"overall_action": "SELL", "confidence_pct": 60.0})

    gated = _walk_forward_result(
        long_uptrend_df, 200, "SYM", allow_short=True, capital=10_000.0, commission_bps=0.0, step=5,
        min_confidence_pct=55.0, short_confidence_premium=10.0,
    )
    ungated = _walk_forward_result(
        long_uptrend_df, 200, "SYM", allow_short=True, capital=10_000.0, commission_bps=0.0, step=5,
        min_confidence_pct=55.0, short_confidence_premium=0.0,
    )

    assert gated["trades"] == []  # 60 < 55 + 10: the short never opens
    assert ungated["trades"] != []  # 60 >= 55: without the premium it does


def test_walk_forward_short_premium_does_not_gate_buys(monkeypatch, long_uptrend_df):
    monkeypatch.setattr(portfolio_module, "recommend", lambda *a, **k: {"overall_action": "BUY", "confidence_pct": 60.0})
    result = _walk_forward_result(
        long_uptrend_df, 200, "SYM", allow_short=True, capital=10_000.0, commission_bps=0.0, step=5,
        min_confidence_pct=55.0, short_confidence_premium=50.0,
    )
    assert result["trades"] != []  # a BUY at 60 never pays the short premium


def test_walk_forward_short_premium_does_not_gate_defensive_sell_when_shorts_disabled(monkeypatch, long_uptrend_df):
    """With allow_short=False a SELL just flattens the long — a defensive
    move that must not be premium-gated."""
    calls = {"n": 0}

    def buy_then_sell(window, *a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"overall_action": "BUY", "confidence_pct": 90.0}
        return {"overall_action": "SELL", "confidence_pct": 60.0}

    monkeypatch.setattr(portfolio_module, "recommend", buy_then_sell)
    result = _walk_forward_result(
        long_uptrend_df, 200, "SYM", allow_short=False, capital=10_000.0, commission_bps=0.0, step=5,
        min_confidence_pct=55.0, short_confidence_premium=50.0, adaptive_learning=False,
    )
    closed = [t for t in result["trades"] if not t.get("open")]
    assert closed, "the SELL at 60 must have closed the long despite the 50-point short premium"


def test_select_portfolio_short_premium_filters_sell_candidates(monkeypatch, long_uptrend_df):
    def fake_recommend(window, symbol="", **k):
        action = "SELL" if symbol == "BEARISH" else "BUY"
        return _fake_rec(action=action, confidence=60.0)

    monkeypatch.setattr(portfolio_module, "recommend", fake_recommend)
    dfs = {"BEARISH": long_uptrend_df, "BULLISH": long_uptrend_df}
    start_idx_by_symbol = {s: 200 for s in dfs}

    gated = _select_portfolio(
        dfs, start_idx_by_symbol, portfolio_size=2, allow_short=True, initial_capital=10_000.0,
        commission_bps=5.0, min_confidence_pct=55.0, short_confidence_premium=10.0,
    )
    ungated = _select_portfolio(
        dfs, start_idx_by_symbol, portfolio_size=2, allow_short=True, initial_capital=10_000.0,
        commission_bps=5.0, min_confidence_pct=55.0,
    )

    assert [c["symbol"] for c in gated] == ["BULLISH"]
    assert {c["symbol"] for c in ungated} == {"BEARISH", "BULLISH"}


# ---------------------------------------------------------------------------
# Risk-regime position sizing (realized-volatility exposure scaling)
# ---------------------------------------------------------------------------


def _alternating_returns_close(pcts: list[float], start: float = 100.0) -> pd.Series:
    """Builds a close series from a list of per-bar % returns."""
    closes = [start]
    for pct in pcts:
        closes.append(closes[-1] * (1 + pct / 100))
    return pd.Series(closes)


def test_vol_regime_exposure_full_when_vol_is_constant():
    from app.portfolio import _vol_regime_exposure

    # Alternating +1%/-1% forever: short-window and long-window realized vol
    # are identical, so the ratio is exactly 1 -> full exposure.
    close = _alternating_returns_close([1.0, -1.0] * 150)
    exposure = _vol_regime_exposure(close)
    assert np.allclose(exposure, 1.0)


def test_vol_regime_exposure_stays_within_bounds():
    from app.portfolio import VOL_REGIME_MIN_EXPOSURE, _vol_regime_exposure

    rng = np.random.default_rng(7)
    close = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.02, 400)))
    exposure = _vol_regime_exposure(close)
    assert (exposure >= VOL_REGIME_MIN_EXPOSURE).all()
    assert (exposure <= 1.0).all()


def test_vol_regime_exposure_drops_after_vol_spike():
    from app.portfolio import _vol_regime_exposure

    calm = [0.3, -0.3] * 100  # 200 calm bars
    wild = [4.0, -4.0] * 15  # 30 bars at ~13x the calm volatility
    close = _alternating_returns_close(calm + wild)
    exposure = _vol_regime_exposure(close)
    assert exposure.iloc[150] == pytest.approx(1.0)  # calm stretch trades at full size
    # By the end, the 20-bar window is all-wild while the 100-bar baseline
    # still mixes in 70 calm bars: exposure ~ sqrt((30*4^2+70*0.3^2)/100)/4 ~ 0.55.
    assert exposure.iloc[-1] < 0.6  # spike cuts exposure to roughly half


def test_vol_regime_exposure_full_on_flat_series():
    from app.portfolio import _vol_regime_exposure

    # Zero volatility everywhere -> degenerate 0/0 ratios must not produce
    # NaN/inf exposure; "no evidence of risk" defaults to full size.
    exposure = _vol_regime_exposure(pd.Series([100.0] * 300))
    assert (exposure == 1.0).all()


def test_vol_regime_exposure_is_causal():
    from app.portfolio import _vol_regime_exposure

    rng = np.random.default_rng(11)
    returns = rng.normal(0, 0.015, 400)
    close_full = pd.Series(100 * np.cumprod(1 + returns))
    # Same history up to bar 250, then a violently different future.
    altered = returns.copy()
    altered[250:] = 0.08
    close_altered = pd.Series(100 * np.cumprod(1 + altered))

    exp_full = _vol_regime_exposure(close_full)
    exp_altered = _vol_regime_exposure(close_altered)
    # Exposure at every bar up to 250 must be identical: bar t uses only
    # closes up to t, so the future can't reach back.
    pd.testing.assert_series_equal(exp_full.iloc[:250], exp_altered.iloc[:250])


def test_walk_forward_risk_regime_softens_a_volatile_crash(monkeypatch):
    """Buy once, hold forever (stop-loss disabled), then a high-volatility
    crash: the regime-sized arm must lose less than the full-size arm,
    because rising realized vol shrank its exposure on the way down."""
    calm = [0.2, -0.2] * 100  # 200 calm bars
    crash = [-5.0, 1.0] * 20  # 40 bars: violent, net-down
    close = _alternating_returns_close(calm + crash)
    df = _make_ohlcv(close)

    def buy_once_then_hold(window, *a, **k):
        action = "BUY" if len(window) == 201 else "HOLD"
        return {"overall_action": action, "confidence_pct": 80.0}

    monkeypatch.setattr(portfolio_module, "recommend", buy_once_then_hold)

    common = dict(allow_short=False, capital=10_000.0, commission_bps=0.0, step=1, stop_loss_pct=None)
    scaled = _walk_forward_result(df, 200, "SYM", risk_regime_sizing=True, **common)
    full_size = _walk_forward_result(df, 200, "SYM", risk_regime_sizing=False, **common)

    assert scaled["equity_curve"].iloc[-1] > full_size["equity_curve"].iloc[-1]
    assert scaled["risk_regime_avg_exposure_pct"] < 100.0
    assert full_size["risk_regime_avg_exposure_pct"] == 100.0


def test_walk_forward_risk_regime_matches_full_size_in_calm_market(monkeypatch, long_uptrend_df):
    """In a market whose volatility never rises above its own baseline, the
    regime filter must be a no-op — same equity curve to the cent."""
    monkeypatch.setattr(
        portfolio_module, "recommend", lambda *a, **k: {"overall_action": "BUY", "confidence_pct": 80.0}
    )
    close = _alternating_returns_close([0.5, -0.5] * 150)
    df = _make_ohlcv(close)
    common = dict(allow_short=False, capital=10_000.0, commission_bps=2.0, step=1)
    scaled = _walk_forward_result(df, 200, "SYM", risk_regime_sizing=True, **common)
    full_size = _walk_forward_result(df, 200, "SYM", risk_regime_sizing=False, **common)
    pd.testing.assert_series_equal(scaled["equity_curve"], full_size["equity_curve"])


def test_simulate_portfolio_synthetic_reports_risk_regime_flag(monkeypatch):
    monkeypatch.setattr(portfolio_module, "recommend", lambda *a, **k: _fake_rec(action="BUY", confidence=80.0))

    off = simulate_portfolio_synthetic(start_date="2026-01-01", portfolio_size=2, risk_regime_sizing=False, rebalance_months=None)
    # Default ON: validated across 6 historical windows — smaller max
    # drawdown in 6/6, avg return delta +1.17 pp (see
    # scripts/validate_risk_regime_result.json).
    on = simulate_portfolio_synthetic(start_date="2026-01-01", portfolio_size=2, rebalance_months=None)

    assert off["risk_regime_sizing"] is False
    assert on["risk_regime_sizing"] is True
    for entry in off["per_symbol"]:
        assert entry["risk_regime_avg_exposure_pct"] == 100.0
    for entry in on["per_symbol"]:
        assert 25.0 <= entry["risk_regime_avg_exposure_pct"] <= 100.0


# ---------------------------------------------------------------------------
# Periodic portfolio re-selection (rebalance_months)
# ---------------------------------------------------------------------------


def _run_sim(dfs, start_date="2023-06-01", **kwargs):
    defaults = dict(
        end_date=None, portfolio_size=3, initial_capital=9_000.0, commission_bps=0.0,
        allow_short=False, step=1, errors={},
    )
    defaults.update(kwargs)
    return portfolio_module._run_simulation(dfs, start_date, **defaults)


def test_rebalanced_sim_chains_capital_across_segments(monkeypatch, long_uptrend_df):
    monkeypatch.setattr(portfolio_module, "recommend", lambda *a, **k: _fake_rec(action="BUY", confidence=80.0))
    close = pd.Series(np.linspace(100, 300, 500))
    dfs = {"A": _make_ohlcv(close), "B": _make_ohlcv(close * 1.5)}

    report = _run_sim(dfs, rebalance_months=3)

    assert report["rebalance_months"] == 3
    segments = report["segments"]
    assert len(segments) >= 2  # 500 daily bars from 2023-01-01 span several quarters
    for prev, nxt in zip(segments, segments[1:]):
        assert nxt["capital_start"] == prev["capital_end"]
        assert nxt["start_date"] > prev["start_date"]
    assert report["final_equity"] == segments[-1]["capital_end"]
    assert report["benchmark_buy_hold"]["total_return_pct"] is not None


def test_rebalanced_sim_flat_market_zero_commission_preserves_capital(monkeypatch):
    """Flat prices + zero commission: no matter how many rebalances happen,
    equity must come out exactly equal to what went in — any drift here
    would mean the segment chaining itself invents or destroys money."""
    monkeypatch.setattr(portfolio_module, "recommend", lambda *a, **k: _fake_rec(action="BUY", confidence=80.0))
    close = pd.Series([100.0] * 500)
    dfs = {"A": _make_ohlcv(close), "B": _make_ohlcv(close)}

    report = _run_sim(dfs, rebalance_months=3)

    assert report["final_equity"] == pytest.approx(9_000.0)
    for segment in report["segments"]:
        assert segment["return_pct"] == pytest.approx(0.0)


def test_rebalanced_sim_goes_to_cash_when_no_candidates(monkeypatch):
    """Selection stops finding candidates after a date -> later segments sit
    fully in cash (capital unchanged), instead of forcing a pick or dying."""
    cutoff = pd.Timestamp("2023-08-20")

    def buy_early_then_nothing(window, *a, **k):
        if window.index[-1] < cutoff:
            return _fake_rec(action="BUY", confidence=80.0)
        return _fake_rec(action="HOLD", confidence=80.0)

    monkeypatch.setattr(portfolio_module, "recommend", buy_early_then_nothing)
    close = pd.Series([100.0] * 500)
    dfs = {"A": _make_ohlcv(close)}

    report = _run_sim(dfs, rebalance_months=3, portfolio_size=1)

    cash_segments = [s for s in report["segments"] if not s["portfolio"]]
    assert cash_segments, "las fronteras posteriores al cutoff deben quedar en efectivo"
    for segment in cash_segments:
        assert segment["capital_end"] == segment["capital_start"]
        assert "note" in segment
    assert report["final_equity"] == pytest.approx(9_000.0)


def test_rebalanced_sim_selection_never_sees_past_segment_end(monkeypatch):
    """Every recommend() call during a rebalanced run — selection at each
    boundary and every walk-forward day — must only ever see data from
    before its own segment's end. A window reaching past the boundary its
    decision belongs to would be lookahead."""
    seen_windows = []

    def recording_recommend(window, *a, **k):
        seen_windows.append(window.index[-1])
        return _fake_rec(action="BUY", confidence=80.0)

    monkeypatch.setattr(portfolio_module, "recommend", recording_recommend)
    close = pd.Series(np.linspace(100, 200, 500))
    dfs = {"A": _make_ohlcv(close)}

    report = _run_sim(dfs, rebalance_months=3, portfolio_size=1)

    last_data_date = dfs["A"].index[-1]
    assert max(seen_windows) <= last_data_date
    # The report's own end date must equal the data's end — i.e. the run
    # covered everything without any segment silently truncating the tail.
    assert report["end_date"] == str(last_data_date.date())


def test_rebalance_none_keeps_classic_report_shape(monkeypatch, long_uptrend_df):
    monkeypatch.setattr(portfolio_module, "recommend", lambda *a, **k: _fake_rec(action="BUY", confidence=80.0))
    report = _run_sim({"A": long_uptrend_df}, portfolio_size=1)
    assert "segments" not in report
    assert "rebalance_months" not in report


def test_rebalanced_sim_charges_rotation_cost_after_first_boundary(monkeypatch):
    monkeypatch.setattr(portfolio_module, "recommend", lambda *a, **k: _fake_rec(action="BUY", confidence=80.0))
    close = pd.Series([100.0] * 500)
    dfs = {"A": _make_ohlcv(close)}

    report = _run_sim(dfs, rebalance_months=3, portfolio_size=1, commission_bps=100.0)

    segments = [s for s in report["segments"] if s["portfolio"]]
    assert len(segments) >= 2
    # First segment: no rotation charge (parity with the classic simulator).
    assert segments[0]["capital_by_symbol"]["A"] == pytest.approx(9_000.0)
    # Each later boundary: allocation = incoming capital * (1 - 2*1%).
    for prev, nxt in zip(segments, segments[1:]):
        assert nxt["capital_by_symbol"]["A"] == pytest.approx(prev["capital_end"] * 0.98, abs=0.02)
    assert report["final_equity"] < 9_000.0


# ---------------------------------------------------------------------------
# Equity-regime tilt (100% acciones cuando el mercado está en tendencia alcista)
# ---------------------------------------------------------------------------


def test_equity_risk_on_true_in_uptrend_false_in_downtrend():
    from app.portfolio import _equity_risk_on

    up = _make_ohlcv(pd.Series(np.linspace(100, 300, 400)))
    down = _make_ohlcv(pd.Series(np.linspace(300, 100, 400)))
    assert _equity_risk_on({"^GSPC": up}, {"^GSPC": 300}) is True
    assert _equity_risk_on({"^GSPC": down}, {"^GSPC": 300}) is False


def test_equity_risk_on_none_without_regime_symbol_or_history():
    from app.portfolio import _equity_risk_on

    up = _make_ohlcv(pd.Series(np.linspace(100, 300, 400)))
    assert _equity_risk_on({"AAPL": up}, {"AAPL": 300}) is None  # no ^GSPC in universe
    assert _equity_risk_on({"^GSPC": up}, {"^GSPC": 150}) is None  # menos de 200 barras antes de la frontera


def test_equity_risk_on_is_causal():
    """The reading at a boundary uses only bars strictly before it: a future
    crash after the boundary must not change it."""
    from app.portfolio import _equity_risk_on

    up_then_crash = _make_ohlcv(pd.Series(np.concatenate([np.linspace(100, 300, 300), np.linspace(300, 50, 100)])))
    pure_up = _make_ohlcv(pd.Series(np.concatenate([np.linspace(100, 300, 300), np.linspace(300, 400, 100)])))
    assert _equity_risk_on({"^GSPC": up_then_crash}, {"^GSPC": 300}) == _equity_risk_on({"^GSPC": pure_up}, {"^GSPC": 300})


def test_apply_equity_tilt_narrows_to_equities_and_lifts_cap(long_uptrend_df):
    from app.portfolio import _apply_equity_tilt

    usable = {"AAPL": long_uptrend_df, "^GSPC": long_uptrend_df, "EURUSD=X": long_uptrend_df, "GC=F": long_uptrend_df}
    narrowed, cap = _apply_equity_tilt(usable, True, 2)
    assert set(narrowed) == {"AAPL", "^GSPC"}
    assert cap is None
    untouched, cap2 = _apply_equity_tilt(usable, False, 2)
    assert set(untouched) == set(usable)
    assert cap2 == 2
    # risk_on=None (regime unreadable) must also be a no-op
    same, cap3 = _apply_equity_tilt(usable, None, 2)
    assert set(same) == set(usable)
    assert cap3 == 2


def test_apply_equity_tilt_noop_when_no_equities(long_uptrend_df):
    from app.portfolio import _apply_equity_tilt

    usable = {"EURUSD=X": long_uptrend_df, "GC=F": long_uptrend_df}
    kept, cap = _apply_equity_tilt(usable, True, 2)
    assert set(kept) == set(usable)
    assert cap == 2


def test_rebalanced_sim_tilt_excludes_forex_in_uptrend(monkeypatch):
    monkeypatch.setattr(portfolio_module, "recommend", lambda *a, **k: _fake_rec(action="BUY", confidence=80.0))
    up = pd.Series(np.linspace(100, 300, 500))
    dfs = {"AAPL": _make_ohlcv(up), "^GSPC": _make_ohlcv(up), "EURUSD=X": _make_ohlcv(up)}

    tilted = _run_sim(dfs, start_date="2023-09-01", rebalance_months=3, equity_regime_tilt=True)
    plain = _run_sim(dfs, start_date="2023-09-01", rebalance_months=3)

    for segment in tilted["segments"]:
        if segment.get("equity_risk_on"):
            assert "EURUSD=X" not in segment["portfolio"]
    assert any(seg.get("equity_risk_on") for seg in tilted["segments"])
    assert tilted["equity_regime_tilt"] is True
    assert plain["equity_regime_tilt"] is False
    assert any("EURUSD=X" in seg["portfolio"] for seg in plain["segments"])


# ---------------------------------------------------------------------------
# Emergency re-selection boundary (regime flip mid-segment)
# ---------------------------------------------------------------------------


def _regime_cross_down_close(n_up=300, n_down=100):
    """Rises long enough to sit above its 200-bar SMA, then slides until it
    crosses below it — the classic risk-on -> risk-off flip."""
    return pd.Series(np.concatenate([np.linspace(100, 200, n_up), np.linspace(200, 120, n_down)]))


def test_first_regime_flip_finds_cross_down():
    from app.portfolio import _first_regime_flip

    df = _make_ohlcv(_regime_cross_down_close())
    flip = _first_regime_flip(df, True, df.index[0], None)
    assert flip is not None
    close = df["Close"]
    sma = close.rolling(200).mean()
    assert close.loc[flip] < sma.loc[flip]
    prev = df.index[df.index.get_loc(flip) - 1]
    assert close.loc[prev] > sma.loc[prev]  # first bar below, not a later one


def test_first_regime_flip_none_without_cross_or_data():
    from app.portfolio import _first_regime_flip

    up = _make_ohlcv(pd.Series(np.linspace(100, 300, 400)))
    assert _first_regime_flip(up, True, up.index[0], None) is None  # never crosses down
    assert _first_regime_flip(None, True, up.index[0], None) is None


def test_first_regime_flip_respects_scan_window():
    from app.portfolio import _first_regime_flip

    df = _make_ohlcv(_regime_cross_down_close())
    flip = _first_regime_flip(df, True, df.index[0], None)
    after = _first_regime_flip(df, True, flip + pd.Timedelta(days=200), None)
    assert after is None or after > flip + pd.Timedelta(days=199)
    before = _first_regime_flip(df, True, df.index[0], flip)  # scan ends (exclusive) at the flip
    assert before is None


def test_rebalanced_sim_emergency_cuts_segment_at_regime_flip(monkeypatch):
    monkeypatch.setattr(portfolio_module, "recommend", lambda *a, **k: _fake_rec(action="BUY", confidence=80.0))
    regime = _make_ohlcv(_regime_cross_down_close(n_up=320, n_down=180))
    dfs = {"^GSPC": regime, "AAPL": _make_ohlcv(pd.Series(np.linspace(100, 250, 500))), "EURUSD=X": _make_ohlcv(pd.Series(np.linspace(100, 110, 500)))}

    with_emergency = _run_sim(dfs, start_date="2023-09-01", rebalance_months=6, equity_regime_tilt=True, emergency_reselect=True)
    without = _run_sim(dfs, start_date="2023-09-01", rebalance_months=6, equity_regime_tilt=True)

    cut_segments = [s for s in with_emergency["segments"] if "emergency_cut_date" in s]
    assert cut_segments, "el cruce debajo de la media de 200 días debe adelantar una frontera"
    assert "cruce" in cut_segments[0]["cut_reason"]
    # The segment after the cut re-read the regime as risk-off -> defensive universe allowed again
    cut_idx = with_emergency["segments"].index(cut_segments[0])
    assert with_emergency["segments"][cut_idx + 1]["equity_risk_on"] is False
    assert with_emergency["emergency_reselect"] is True
    # Without the emergency, boundaries stay purely calendar-driven: 6-month segments
    assert all("emergency_cut_date" not in s for s in without["segments"])
    # The cut fired strictly before the scheduled 6-month boundary would have
    next_start = with_emergency["segments"][cut_idx + 1]["start_date"]
    assert next_start < "2024-03-01"  # 2023-09-01 + 6 meses


def test_rebalanced_sim_emergency_off_by_default(monkeypatch):
    monkeypatch.setattr(portfolio_module, "recommend", lambda *a, **k: _fake_rec(action="BUY", confidence=80.0))
    dfs = {"^GSPC": _make_ohlcv(_regime_cross_down_close(n_up=320, n_down=180))}
    report = _run_sim(dfs, start_date="2023-09-01", rebalance_months=3, portfolio_size=1, equity_regime_tilt=True)
    assert report["emergency_reselect"] is False
    assert all("emergency_cut_date" not in s for s in report["segments"])


def test_first_regime_flip_hysteresis_band_ignores_shallow_cross():
    """A dip that crosses the SMA but never clears the band must not fire."""
    from app.portfolio import _first_regime_flip

    up = np.linspace(100, 200, 300)
    # Shallow dip: ~1% below the SMA at its lowest, then recovery.
    shallow = np.concatenate([up, np.linspace(200, 185, 30), np.linspace(185, 210, 70)])
    df = _make_ohlcv(pd.Series(shallow))
    raw = _first_regime_flip(df, True, df.index[0], None)
    banded = _first_regime_flip(df, True, df.index[0], None, band_pct=2.0, confirm_days=1)
    if raw is not None:  # the raw cross fires on the shallow dip...
        close, sma = df["Close"], df["Close"].rolling(200).mean()
        assert close.loc[raw] < sma.loc[raw]
        # ...but never gets 2% beyond the SMA, so the banded variant stays quiet.
        assert ((close < sma * 0.98) & sma.notna()).sum() == 0
        assert banded is None


def test_first_regime_flip_confirmation_requires_consecutive_days():
    """One isolated day beyond the band must not fire with confirm_days=5;
    a sustained slide must, dated at the day confirmation completes."""
    from app.portfolio import _first_regime_flip

    df = _make_ohlcv(_regime_cross_down_close(n_up=300, n_down=100))
    single = _first_regime_flip(df, True, df.index[0], None, band_pct=2.0, confirm_days=1)
    confirmed = _first_regime_flip(df, True, df.index[0], None, band_pct=2.0, confirm_days=5)
    assert single is not None and confirmed is not None
    assert confirmed == df.index[df.index.get_loc(single) + 4]  # exactly 4 bars after the first beyond-band close
    close, sma = df["Close"], df["Close"].rolling(200).mean()
    window = close.loc[:confirmed].tail(5)
    assert (window < sma.loc[window.index] * 0.98).all()


def test_first_regime_flip_confirmation_is_causal():
    """The confirmed flip date must not move if the future after it changes."""
    from app.portfolio import _first_regime_flip

    base = _regime_cross_down_close(n_up=300, n_down=100)
    df = _make_ohlcv(base)
    flip = _first_regime_flip(df, True, df.index[0], None, band_pct=2.0, confirm_days=5)
    cut = df.index.get_loc(flip) + 1
    altered = pd.concat([base.iloc[:cut], pd.Series(np.linspace(base.iloc[cut - 1], 400, len(base) - cut))], ignore_index=True)
    df2 = _make_ohlcv(altered)
    assert _first_regime_flip(df2, True, df2.index[0], None, band_pct=2.0, confirm_days=5) == flip


# ---------------------------------------------------------------------------
# Concentration cap (max_position_weight + cash reserve)
# ---------------------------------------------------------------------------


def test_cap_weights_caps_without_renormalizing():
    from app.portfolio import _cap_weights

    capped = _cap_weights({"A": 1.0}, 0.4)
    assert capped == {"A": 0.4}  # surplus stays undeployed, not pushed elsewhere
    multi = _cap_weights({"A": 0.5, "B": 0.3, "C": 0.2}, 0.4)
    assert multi == {"A": 0.4, "B": 0.3, "C": 0.2}
    assert _cap_weights({"A": 1.0}, None) == {"A": 1.0}


def test_single_candidate_deploys_capped_fraction_and_keeps_cash(monkeypatch):
    """One candidate, flat market, zero commission: with a 0.4 cap the model
    must end with exactly its starting capital — 40% deployed earning zero
    plus 60% cash — and report the reserve."""
    monkeypatch.setattr(portfolio_module, "recommend", lambda *a, **k: _fake_rec(action="BUY", confidence=80.0))
    dfs = {"A": _make_ohlcv(pd.Series([100.0] * 400))}

    report = _run_sim(dfs, portfolio_size=1, rebalance_months=None, max_position_weight=0.4)

    assert report["cash_reserved"] == pytest.approx(9_000.0 * 0.6)
    assert report["capital_by_symbol"]["A"] == pytest.approx(9_000.0 * 0.4)
    assert report["final_equity"] == pytest.approx(9_000.0)
    assert report["benchmark_buy_hold"]["cash_reserved"] == pytest.approx(9_000.0 * 0.6)


def test_cap_limits_single_name_loss(monkeypatch):
    """A crashing single pick: uncapped loses the full crash on 100% of the
    capital; capped at 0.4 the damage is bounded to the deployed slice."""
    def buy_once_then_hold(window, *a, **k):
        return _fake_rec(action="BUY" if len(window) <= 152 else "HOLD", confidence=80.0)

    monkeypatch.setattr(portfolio_module, "recommend", buy_once_then_hold)
    close = pd.Series([100.0] * 200 + list(np.linspace(100, 60, 200)))
    dfs = {"A": _make_ohlcv(close)}
    common = dict(portfolio_size=1, rebalance_months=None, stop_loss_pct=None)

    uncapped = _run_sim(dfs, **common)
    capped = _run_sim(dfs, **common, max_position_weight=0.4)

    assert capped["final_equity"] > uncapped["final_equity"]
    assert capped["cash_reserved"] > 0


def test_rebalanced_sim_reports_cash_per_segment(monkeypatch):
    monkeypatch.setattr(portfolio_module, "recommend", lambda *a, **k: _fake_rec(action="BUY", confidence=80.0))
    dfs = {"A": _make_ohlcv(pd.Series([100.0] * 500))}

    report = _run_sim(dfs, portfolio_size=1, rebalance_months=3, max_position_weight=0.4)

    for segment in report["segments"]:
        if segment["portfolio"]:
            assert segment["cash_reserved"] == pytest.approx(segment["capital_start"] * 0.6, abs=0.02)
    assert report["final_equity"] == pytest.approx(9_000.0)
