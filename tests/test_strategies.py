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
