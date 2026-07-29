"""Cross-cutting checks that commission_bps=None resolves to a realistic,
per-instrument default (see app.config.DEFAULT_COMMISSION_BPS) everywhere
it's threaded through, instead of one flat guess for every asset class."""

from app.backtest.engine import run_backtest
from app.config import default_commission_bps
from app.opportunities import find_opportunities_synthetic
from app.ranking import build_symbol_strategy_matrix
from app.recommend.engine import recommend
from app.simulate import simulate
from app.strategies import build_strategy


def test_run_backtest_resolves_default_commission_per_symbol(uptrend_df):
    strategy = build_strategy("sma_crossover")
    result_stock = run_backtest(uptrend_df, strategy, symbol="AAPL")
    result_crypto = run_backtest(uptrend_df, strategy, symbol="BTC-USD")

    assert result_stock.metrics["total_return_pct"] != result_crypto.metrics["total_return_pct"]
    # Higher commission (crypto) should never outperform an identical price
    # series backtested with a lower commission (stock), trade-for-trade.
    assert result_crypto.metrics["total_return_pct"] <= result_stock.metrics["total_return_pct"]


def test_run_backtest_explicit_commission_overrides_default(uptrend_df):
    strategy = build_strategy("sma_crossover")
    explicit = run_backtest(uptrend_df, strategy, symbol="BTC-USD", commission_bps=default_commission_bps("AAPL"))
    stock_default = run_backtest(uptrend_df, strategy, symbol="AAPL")
    assert explicit.metrics["total_return_pct"] == stock_default.metrics["total_return_pct"]


def test_recommend_accepts_none_commission_without_crashing(random_walk_df):
    result = recommend(random_walk_df, symbol="EURUSD=X", commission_bps=None)
    assert result["overall_action"] in ("BUY", "SELL", "HOLD")


def test_simulate_echoes_resolved_commission_in_report(uptrend_df):
    report = simulate(uptrend_df, strategy_name="sma_crossover", symbol="BTC-USD", commission_bps=None)
    assert report["commission_bps"] == default_commission_bps("BTC-USD")


def test_ranking_matrix_resolves_commission_per_symbol_label(uptrend_df, downtrend_df):
    dfs = {"AAPL": uptrend_df, "BTC-USD": downtrend_df}
    result = build_symbol_strategy_matrix(dfs, commission_bps=None)
    assert len(result["matrix"]) > 0  # no crash; per-symbol resolution happens inside run_backtest


def test_opportunities_synthetic_runs_with_default_commission_resolution():
    # Synthetic profile labels aren't real tickers, so they all fall back to
    # the STOCK default — this just guards against a crash/regression.
    report = find_opportunities_synthetic(top_n=2)
    assert report["evaluated"] == 5
