import pandas as pd

from app.backtest.engine import compare_strategies, run_backtest
from app.backtest.metrics import compute_metrics
from app.strategies import all_strategies, build_strategy


def test_compute_metrics_matches_manual_calculation():
    equity_curve = pd.Series([100.0, 110.0, 121.0])
    strategy_returns = pd.Series([0.0, 0.10, 0.10])
    trades = [
        {"return_pct": 10.0},
        {"return_pct": -5.0},
    ]

    metrics = compute_metrics(equity_curve, trades, strategy_returns)

    assert metrics["total_return_pct"] == 21.0
    assert metrics["max_drawdown_pct"] == 0.0
    assert metrics["num_trades"] == 2
    assert metrics["win_rate_pct"] == 50.0
    assert metrics["avg_profit_per_trade_pct"] == 2.5
    assert metrics["best_trade_pct"] == 10.0
    assert metrics["worst_trade_pct"] == -5.0
    assert metrics["avg_win_pct"] == 10.0
    assert metrics["avg_loss_pct"] == -5.0
    assert metrics["profit_factor"] == 2.0


def test_compute_metrics_handles_no_trades():
    equity_curve = pd.Series([100.0, 100.0, 100.0])
    strategy_returns = pd.Series([0.0, 0.0, 0.0])
    metrics = compute_metrics(equity_curve, [], strategy_returns)
    assert metrics["num_trades"] == 0
    assert metrics["win_rate_pct"] == 0.0
    assert metrics["profit_factor"] is None


def test_run_backtest_returns_expected_shape(random_walk_df):
    strategy = build_strategy("sma_crossover", fast=10, slow=30)
    result = run_backtest(random_walk_df, strategy, symbol="TEST")

    assert result.symbol == "TEST"
    assert len(result.equity_curve) == len(random_walk_df)
    expected_keys = {
        "total_return_pct",
        "cagr_pct",
        "max_drawdown_pct",
        "sharpe_ratio",
        "num_trades",
        "win_rate_pct",
        "avg_profit_per_trade_pct",
        "best_trade_pct",
        "worst_trade_pct",
        "avg_win_pct",
        "avg_loss_pct",
        "profit_factor",
    }
    assert expected_keys.issubset(result.metrics.keys())
    for trade in result.trades:
        assert trade["exit_price"] > 0
        assert trade["entry_price"] > 0


def test_run_backtest_rejects_too_little_data(random_walk_df):
    strategy = build_strategy("sma_crossover")
    try:
        run_backtest(random_walk_df.iloc[:3], strategy)
        assert False, "debería haber lanzado ValueError"
    except ValueError:
        pass


def test_compare_strategies_is_sorted_by_avg_profit_per_trade(random_walk_df):
    results = compare_strategies(random_walk_df, all_strategies(), symbol="TEST")
    profits = [r.metrics["avg_profit_per_trade_pct"] for r in results]
    assert profits == sorted(profits, reverse=True)
    assert len(results) == len(all_strategies())
