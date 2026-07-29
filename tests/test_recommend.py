from app.recommend.engine import recommend
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
