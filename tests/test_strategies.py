import pytest

from app.strategies import STRATEGY_REGISTRY, all_strategies, build_strategy


@pytest.mark.parametrize("name", list(STRATEGY_REGISTRY))
def test_strategy_positions_are_binary(name, random_walk_df):
    strategy = build_strategy(name)
    enriched = strategy.run(random_walk_df)
    assert set(enriched["position"].unique()).issubset({0, 1})


@pytest.mark.parametrize("name", list(STRATEGY_REGISTRY))
def test_strategy_latest_signal_shape(name, random_walk_df):
    strategy = build_strategy(name)
    signal = strategy.latest_signal(random_walk_df)
    assert signal["action"] in {"BUY", "SELL", "HOLD_LONG", "HOLD_CASH"}
    assert signal["strategy"] == strategy.name
    assert isinstance(signal["details"], dict)


def test_sma_crossover_goes_long_on_sustained_uptrend(uptrend_df):
    strategy = build_strategy("sma_crossover", fast=5, slow=20)
    enriched = strategy.run(uptrend_df)
    assert enriched["position"].iloc[-1] == 1


def test_build_strategy_rejects_unknown_name():
    with pytest.raises(ValueError):
        build_strategy("does_not_exist")


def test_all_strategies_returns_one_of_each():
    strategies = all_strategies()
    assert len(strategies) == len(STRATEGY_REGISTRY)
