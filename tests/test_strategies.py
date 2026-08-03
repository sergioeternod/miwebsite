import pytest

from app.strategies import STRATEGY_REGISTRY, all_strategies, build_strategy

ALL_ACTIONS = {"BUY", "SELL", "SELL_SHORT", "COVER", "HOLD_LONG", "HOLD_SHORT", "HOLD_CASH"}


@pytest.mark.parametrize("name", list(STRATEGY_REGISTRY))
def test_strategy_positions_are_within_range(name, random_walk_df):
    strategy = build_strategy(name)
    enriched = strategy.run(random_walk_df)
    assert set(enriched["position"].unique()).issubset({-1, 0, 1})


@pytest.mark.parametrize("name", list(STRATEGY_REGISTRY))
def test_strategy_long_only_never_shorts(name, random_walk_df):
    strategy = build_strategy(name, allow_short=False)
    enriched = strategy.run(random_walk_df)
    assert set(enriched["position"].unique()).issubset({0, 1})


@pytest.mark.parametrize("name", list(STRATEGY_REGISTRY))
def test_strategy_latest_signal_shape(name, random_walk_df):
    strategy = build_strategy(name)
    signal = strategy.latest_signal(random_walk_df)
    assert signal["action"] in ALL_ACTIONS
    assert signal["strategy"] == strategy.name
    assert isinstance(signal["details"], dict)


def test_sma_crossover_goes_long_on_sustained_uptrend(uptrend_df):
    strategy = build_strategy("sma_crossover", fast=5, slow=20)
    enriched = strategy.run(uptrend_df)
    assert enriched["position"].iloc[-1] == 1


def test_sma_crossover_goes_short_on_sustained_downtrend(downtrend_df):
    strategy = build_strategy("sma_crossover", fast=5, slow=20, allow_short=True)
    enriched = strategy.run(downtrend_df)
    assert enriched["position"].iloc[-1] == -1


def test_sma_crossover_stays_flat_on_downtrend_when_shorts_disabled(downtrend_df):
    strategy = build_strategy("sma_crossover", fast=5, slow=20, allow_short=False)
    enriched = strategy.run(downtrend_df)
    assert (enriched["position"] >= 0).all()


def test_build_strategy_rejects_unknown_name():
    with pytest.raises(ValueError):
        build_strategy("does_not_exist")


def test_all_strategies_returns_one_of_each():
    strategies = all_strategies()
    assert len(strategies) == len(STRATEGY_REGISTRY)


def test_all_strategies_respects_allow_short_false():
    strategies = all_strategies(allow_short=False)
    assert all(not s.allow_short for s in strategies)


def test_trend_confirmation_goes_long_on_sustained_uptrend(uptrend_df):
    strategy = build_strategy("trend_confirmation", trend_window=20)
    enriched = strategy.run(uptrend_df)
    assert enriched["position"].iloc[-1] == 1
    assert not (enriched["position"] == -1).any()


def test_trend_confirmation_goes_short_on_sustained_downtrend(downtrend_df):
    strategy = build_strategy("trend_confirmation", trend_window=20, allow_short=True)
    enriched = strategy.run(downtrend_df)
    assert enriched["position"].iloc[-1] == -1
    assert not (enriched["position"] == 1).any()


def test_trend_confirmation_stays_flat_on_downtrend_when_shorts_disabled(downtrend_df):
    strategy = build_strategy("trend_confirmation", trend_window=20, allow_short=False)
    enriched = strategy.run(downtrend_df)
    assert (enriched["position"] >= 0).all()


def test_rsi_reversion_short_exits_at_midline_not_opposite_extreme():
    """Regression guard for the short-trap bug: a short entered on an
    overbought turn must close once the RSI returns to its midline — not
    stay open until an oversold bounce, which in a sustained uptrend may
    never come (measured on real data: a single 374-bar short on gold that
    lost -46.8% while the market doubled)."""
    import numpy as np
    import pandas as pd

    # Price ramps hard (RSI pegs overbought), dips enough for the RSI to turn
    # down through 70 and cross the midline (bottoming near RSI 42), then
    # resumes rising. RSI never goes anywhere near oversold (30).
    closes = (
        [100 + 3 * i for i in range(30)]          # strong ramp: RSI >> 70
        + [190 - 1.2 * i for i in range(21)]      # controlled dip: RSI falls through 70, then through 50
        + [166 + 2 * i for i in range(30)]        # uptrend resumes
    )
    close = pd.Series(np.array(closes, dtype=float))
    df = pd.DataFrame(
        {"Open": close, "High": close * 1.005, "Low": close * 0.995, "Close": close, "Volume": 1000}
    )
    df.index = pd.date_range("2024-01-01", periods=len(df), freq="D")

    strategy = build_strategy("rsi_reversion")
    enriched = strategy.run(df)
    rsi_values = enriched["rsi"]

    assert (rsi_values.dropna() > 35).all(), "fixture must never approach oversold for this test to be meaningful"

    positions = enriched["position"]
    went_short = (positions == -1).any()
    assert went_short, "the overbought turn should have opened a short"
    # The old exit rule (oversold bounce only) would keep the short open to
    # the very last bar of this fixture; the midline exit must have closed it.
    assert positions.iloc[-1] != -1, "short must not survive the RSI returning to its midline"
