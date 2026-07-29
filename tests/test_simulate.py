from app.simulate import simulate, simulate_synthetic
from app.strategies import STRATEGY_REGISTRY


def test_simulate_single_strategy_shape(random_walk_df):
    report = simulate(random_walk_df, strategy_name="sma_crossover", symbol="TEST")
    assert len(report["results"]) == 1
    result = report["results"][0]
    assert result["strategy"].startswith("sma_crossover")
    assert len(result["equity_curve"]) == len(random_walk_df)
    assert len(report["price_series"]) == len(random_walk_df)


def test_simulate_all_strategies_ranked(random_walk_df):
    report = simulate(random_walk_df, symbol="TEST")
    assert len(report["results"]) == len(STRATEGY_REGISTRY)
    profits = [r["metrics"]["avg_profit_per_trade_pct"] for r in report["results"]]
    assert profits == sorted(profits, reverse=True)


def test_simulate_synthetic_exercises_both_long_and_short():
    report = simulate_synthetic(strategy_name="sma_crossover", allow_short=True)
    trades = report["results"][0]["trades"]
    directions = {t["direction"] for t in trades}
    assert "long" in directions
    assert "short" in directions
    assert report["regimes"], "el escenario sintético debería exponer sus regímenes"


def test_simulate_synthetic_no_short_only_longs():
    report = simulate_synthetic(strategy_name="sma_crossover", allow_short=False)
    trades = report["results"][0]["trades"]
    assert all(t["direction"] == "long" for t in trades)
