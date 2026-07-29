import pytest

from app.ranking import build_symbol_strategy_matrix, rank_synthetic_profiles
from app.strategies import STRATEGY_REGISTRY, all_strategies


def test_build_symbol_strategy_matrix_shape(random_walk_df, downtrend_df):
    dfs = {"A": random_walk_df, "B": downtrend_df}
    result = build_symbol_strategy_matrix(dfs, all_strategies())

    assert result["symbols"] == ["A", "B"]
    assert len(result["matrix"]) == len(dfs) * len(STRATEGY_REGISTRY)
    assert set(result["best_symbol_per_strategy"]) == {s.name for s in all_strategies()}
    assert set(result["best_strategy_per_symbol"]) == {"A", "B"}


def test_best_symbol_per_strategy_matches_max_in_matrix(random_walk_df, downtrend_df):
    dfs = {"A": random_walk_df, "B": downtrend_df}
    result = build_symbol_strategy_matrix(dfs, all_strategies())

    for strategy_name, best in result["best_symbol_per_strategy"].items():
        rows = [r for r in result["matrix"] if r["strategy"] == strategy_name]
        expected = max(r["metrics"]["avg_profit_per_trade_pct"] for r in rows)
        assert best["avg_profit_per_trade_pct"] == expected


def test_best_strategy_per_symbol_matches_max_in_matrix(random_walk_df, downtrend_df):
    dfs = {"A": random_walk_df, "B": downtrend_df}
    result = build_symbol_strategy_matrix(dfs, all_strategies())

    for symbol, best in result["best_strategy_per_symbol"].items():
        rows = [r for r in result["matrix"] if r["symbol"] == symbol]
        expected = max(r["metrics"]["avg_profit_per_trade_pct"] for r in rows)
        assert best["avg_profit_per_trade_pct"] == expected


def test_rank_synthetic_profiles_end_to_end():
    result = rank_synthetic_profiles()
    assert len(result["symbols"]) == 5
    assert len(result["matrix"]) == 5 * len(STRATEGY_REGISTRY)
    for info in result["best_symbol_per_strategy"].values():
        assert info["symbol"] in result["symbols"]
    for info in result["best_strategy_per_symbol"].values():
        assert info["strategy"] in result["strategies"]


def test_rank_real_symbols_rejects_empty_list():
    from app.ranking import rank_real_symbols

    with pytest.raises(ValueError):
        rank_real_symbols([])
