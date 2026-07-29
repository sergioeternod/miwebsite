import pytest

from app.strategies import STRATEGY_REGISTRY, all_strategies, build_strategy
from app.validation.out_of_sample import out_of_sample_comparison, split_backtest_periods
from app.validation.recommendation_accuracy import walk_forward_recommendation_accuracy
from app.validation.report import build_validation_report, validate_synthetic
from app.validation.trade_accuracy import annotate_trade_hits, compare_directional_accuracy, directional_accuracy


# ---------- out-of-sample ----------


def test_split_backtest_periods_shape(random_walk_df):
    strategy = build_strategy("sma_crossover")
    result = split_backtest_periods(random_walk_df, strategy, split_ratio=0.5, symbol="TEST")

    assert result["strategy"] == strategy.name
    assert result["period_a"]["end"] == result["split_date"] == result["period_b"]["start"]
    assert "avg_profit_per_trade_pct" in result["period_a"]["metrics"]
    assert "avg_profit_per_trade_pct" in result["period_b"]["metrics"]
    assert isinstance(result["consistency"]["profitability_sign_matches"], bool)


def test_split_backtest_periods_rejects_bad_ratio(random_walk_df):
    strategy = build_strategy("sma_crossover")
    with pytest.raises(ValueError):
        split_backtest_periods(random_walk_df, strategy, split_ratio=0.0)
    with pytest.raises(ValueError):
        split_backtest_periods(random_walk_df, strategy, split_ratio=1.0)


def test_period_b_equity_is_rebased_to_initial_capital(random_walk_df):
    strategy = build_strategy("sma_crossover")
    result = split_backtest_periods(random_walk_df, strategy, split_ratio=0.5, initial_capital=10_000.0)
    # Rebasing means period B's own total_return_pct is independent of period A's outcome,
    # i.e. it isn't just a continuation of A's cumulative equity.
    assert "total_return_pct" in result["period_b"]["metrics"]


def test_out_of_sample_comparison_runs_all_strategies(random_walk_df):
    results = out_of_sample_comparison(random_walk_df, all_strategies(), symbol="TEST")
    assert len(results) == len(STRATEGY_REGISTRY)


# ---------- directional accuracy ----------


def test_annotate_trade_hits_matches_direction_and_return():
    trades = [
        {"direction": "long", "return_pct": 5.0},
        {"direction": "long", "return_pct": -3.0},
        {"direction": "short", "return_pct": 2.0},
        {"direction": "short", "return_pct": -1.0},
    ]
    annotated = annotate_trade_hits(trades)
    assert annotated[0]["expected_direction"] == "sube" and annotated[0]["hit"] is True
    assert annotated[1]["expected_direction"] == "sube" and annotated[1]["hit"] is False
    assert annotated[2]["expected_direction"] == "baja" and annotated[2]["hit"] is True
    assert annotated[3]["expected_direction"] == "baja" and annotated[3]["hit"] is False


def test_directional_accuracy_matches_hand_computed_rates():
    trades = [
        {"direction": "long", "return_pct": 5.0},
        {"direction": "long", "return_pct": -3.0},
        {"direction": "short", "return_pct": 2.0},
    ]
    accuracy = directional_accuracy(trades)
    assert accuracy["num_trades"] == 3
    assert accuracy["hit_rate_pct"] == pytest.approx(66.67, abs=0.01)
    assert accuracy["long_hit_rate_pct"] == pytest.approx(50.0)
    assert accuracy["short_hit_rate_pct"] == pytest.approx(100.0)


def test_directional_accuracy_handles_no_trades():
    accuracy = directional_accuracy([])
    assert accuracy["num_trades"] == 0
    assert accuracy["hit_rate_pct"] == 0.0
    assert accuracy["long_hit_rate_pct"] is None
    assert accuracy["short_hit_rate_pct"] is None


def test_compare_directional_accuracy_runs_all_strategies(random_walk_df):
    results = compare_directional_accuracy(random_walk_df, all_strategies(), symbol="TEST")
    assert len(results) == len(STRATEGY_REGISTRY)
    for r in results:
        assert "accuracy" in r and "trades" in r


# ---------- recommendation walk-forward ----------


def test_walk_forward_recommendation_accuracy_shape(random_walk_df):
    result = walk_forward_recommendation_accuracy(random_walk_df, symbol="TEST", horizon=10, step=20, warmup=110)
    assert result["num_evaluations"] == len(result["records"])
    assert result["num_evaluations"] > 0
    for record in result["records"]:
        assert record["action"] in {"BUY", "SELL", "HOLD"}
        assert isinstance(record["forward_return_pct"], float)
    summary = result["summary"]
    assert set(summary.keys()) == {"buy", "sell", "hold"}


def test_walk_forward_rejects_invalid_horizon_or_step(random_walk_df):
    with pytest.raises(ValueError):
        walk_forward_recommendation_accuracy(random_walk_df, horizon=0)
    with pytest.raises(ValueError):
        walk_forward_recommendation_accuracy(random_walk_df, step=0)


# ---------- combined report ----------


def test_build_validation_report_shape(random_walk_df):
    report = build_validation_report(random_walk_df, symbol="TEST", warmup=110, horizon=10, step=20)
    assert len(report["out_of_sample"]) == len(STRATEGY_REGISTRY)
    assert len(report["directional_accuracy"]) == len(STRATEGY_REGISTRY)
    assert report["recommendation_walk_forward"]["num_evaluations"] > 0


def test_build_validation_report_rejects_too_little_data(random_walk_df):
    with pytest.raises(ValueError):
        build_validation_report(random_walk_df.iloc[:50], warmup=110, horizon=10)


def test_validate_synthetic_end_to_end():
    report = validate_synthetic(warmup=110, horizon=10, step=20)
    assert report["symbol"] == "SYNTH"
    assert len(report["out_of_sample"]) == len(STRATEGY_REGISTRY)
