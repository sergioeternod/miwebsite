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


def test_simulate_synthetic_date_range_windows_the_scenario():
    full = simulate_synthetic(strategy_name="sma_crossover")
    windowed = simulate_synthetic(strategy_name="sma_crossover", start_date="2023-04-01", end_date="2023-09-30")

    assert windowed["num_bars"] < full["num_bars"]
    assert windowed["period_start"].startswith("2023-04-01")
    assert windowed["period_end"].startswith("2023-09-30")
    # Every price date must fall inside the requested window.
    assert all("2023-04-01" <= p["date"][:10] <= "2023-09-30" for p in windowed["price_series"])


def test_simulate_synthetic_regimes_remapped_to_window():
    windowed = simulate_synthetic(strategy_name="sma_crossover", start_date="2023-04-01", end_date="2023-09-30")
    n = windowed["num_bars"]
    for _name, start_idx, end_idx in windowed["regimes"]:
        assert 0 <= start_idx <= end_idx < n


def test_simulate_synthetic_invalid_range_raises():
    import pytest

    from app.data.providers import DataUnavailableError

    with pytest.raises(DataUnavailableError):
        simulate_synthetic(strategy_name="sma_crossover", start_date="2030-01-01", end_date="2030-06-01")


def test_simulate_rejects_too_few_bars_after_windowing(random_walk_df):
    import pytest

    with pytest.raises(ValueError):
        simulate(random_walk_df.iloc[:2], strategy_name="sma_crossover")
