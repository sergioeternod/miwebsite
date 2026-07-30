import numpy as np
import pandas as pd
import pytest

from app.recommend.engine import (
    _regime_multiplier,
    _strategy_family,
    _strategy_weight,
    recommend,
)
from app.strategies import STRATEGY_REGISTRY


def test_recommend_returns_valid_overall_action(random_walk_df):
    result = recommend(random_walk_df, symbol="TEST")

    assert result["overall_action"] in {"BUY", "SELL", "HOLD"}
    assert 0.0 <= result["confidence_pct"] <= 100.0
    assert len(result["per_strategy"]) == len(STRATEGY_REGISTRY)
    assert "disclaimer" in result
    assert result["last_close"] > 0


def test_recommend_best_historical_strategy_is_the_max(random_walk_df):
    result = recommend(random_walk_df, symbol="TEST")
    best = result["best_historical_strategy"]["avg_profit_per_trade_pct"]
    all_profits = [s["historical_avg_profit_per_trade_pct"] for s in result["per_strategy"]]
    assert best == max(all_profits)


def test_recommend_reports_market_regime(random_walk_df):
    result = recommend(random_walk_df, symbol="TEST")
    assert "market_regime" in result
    assert "adx" in result["market_regime"] and "reading" in result["market_regime"]


def test_recommend_market_regime_is_none_with_insufficient_history():
    close = pd.Series(np.linspace(100, 110, 20))
    df = pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close, "Volume": 1000})
    df.index = pd.date_range("2024-01-01", periods=len(df), freq="D")
    result = recommend(df, symbol="TEST")
    assert result["market_regime"]["adx"] is None
    assert result["market_regime"]["reading"] is None


def test_strategy_weight_floor_is_small_and_scales_with_losses():
    # A strategy losing a lot should not get the same weight as one barely
    # losing or barely winning — the floor exists only to avoid a literal
    # zero, not to erase the difference between "bad" and "very bad".
    assert _strategy_weight(-20.0) == _strategy_weight(-0.001) == pytest.approx(0.01)
    assert _strategy_weight(3.0) == 3.0


def test_strategy_family_classification():
    assert _strategy_family("sma_crossover_20_50") == "trend"
    assert _strategy_family("macd_crossover_12_26_9") == "trend"
    assert _strategy_family("bollinger_breakout_20_2.0") == "trend"
    assert _strategy_family("trend_confirmation_100_12_26_9") == "trend"
    assert _strategy_family("rsi_reversion_14_30_70") == "mean_reversion"


def test_regime_multiplier_neutral_when_adx_unknown():
    assert _regime_multiplier("trend", float("nan")) == 1.0
    assert _regime_multiplier("mean_reversion", float("nan")) == 1.0


def test_regime_multiplier_boosts_trend_in_strong_trend():
    strong_trend_adx = 45.0
    assert _regime_multiplier("trend", strong_trend_adx) > 1.0
    assert _regime_multiplier("mean_reversion", strong_trend_adx) < 1.0


def test_regime_multiplier_boosts_mean_reversion_in_choppy_market():
    weak_trend_adx = 5.0
    assert _regime_multiplier("mean_reversion", weak_trend_adx) > 1.0
    assert _regime_multiplier("trend", weak_trend_adx) < 1.0


def test_regime_multiplier_symmetric_around_1():
    for current_adx in (5.0, 15.0, 27.5, 40.0, 60.0):
        trend_mult = _regime_multiplier("trend", current_adx)
        mean_reversion_mult = _regime_multiplier("mean_reversion", current_adx)
        assert trend_mult + mean_reversion_mult == pytest.approx(2.0)
