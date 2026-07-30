import pytest

from app.validation.trade_accuracy import annotate_trade_hindsight, hindsight_summary


def _trade(direction, entry_price, exit_price, equity_at_entry=10_000.0, open_=False):
    trade = {
        "direction": direction,
        "entry_date": "2026-01-01",
        "exit_date": "2026-01-10",
        "entry_price": entry_price,
        "exit_price": exit_price,
        "bars_held": 9,
        "return_pct": 0.0,  # not used by the hindsight calc itself
        "pnl_amount": 0.0,
        "equity_at_entry": equity_at_entry,
    }
    if open_:
        trade["open"] = True
    return trade


def test_long_trade_that_went_up_is_optimal():
    trades = annotate_trade_hindsight([_trade("long", 100, 110)])
    h = trades[0]["hindsight"]
    assert h["best_direction"] == "long"
    assert h["was_optimal"] is True
    assert h["regret_pct"] == 0.0


def test_long_trade_that_went_down_was_not_optimal():
    trades = annotate_trade_hindsight([_trade("long", 100, 90)])
    h = trades[0]["hindsight"]
    assert h["best_direction"] == "short"
    assert h["was_optimal"] is False
    assert h["regret_pct"] > 0


def test_short_trade_that_went_down_is_optimal():
    trades = annotate_trade_hindsight([_trade("short", 100, 90)])
    h = trades[0]["hindsight"]
    assert h["best_direction"] == "short"
    assert h["was_optimal"] is True


def test_flat_is_best_when_commission_eats_a_small_move():
    # A tiny 0.1% move barely covers 2 legs of a 20bps commission, so once
    # commission is priced in, staying flat (always 0%) should win.
    trades = annotate_trade_hindsight([_trade("long", 100, 100.1)], commission_bps=20.0)
    h = trades[0]["hindsight"]
    assert h["best_direction"] == "flat"
    assert h["was_optimal"] is False


def test_missed_pnl_amount_scales_with_equity_at_entry():
    trades = annotate_trade_hindsight([_trade("long", 100, 90, equity_at_entry=5_000.0)])
    h = trades[0]["hindsight"]
    expected_missed = round(h["regret_pct"] / 100 * 5_000.0, 2)
    assert h["missed_pnl_amount"] == expected_missed


def test_missed_pnl_amount_none_without_equity_at_entry():
    trade = _trade("long", 100, 90)
    del trade["equity_at_entry"]
    trades = annotate_trade_hindsight([trade])
    assert trades[0]["hindsight"]["missed_pnl_amount"] is None


def test_open_trades_get_no_hindsight_and_are_excluded_from_summary():
    trades = annotate_trade_hindsight([_trade("long", 100, 105, open_=True)])
    assert trades[0]["hindsight"] is None
    assert hindsight_summary(trades)["num_trades"] == 0


def test_hindsight_summary_empty_trades():
    summary = hindsight_summary([])
    assert summary == {
        "num_trades": 0,
        "num_optimal": 0,
        "pct_optimal": None,
        "avg_regret_pct": None,
        "total_missed_pnl_amount": None,
    }


def test_hindsight_summary_aggregates_across_trades():
    trades = annotate_trade_hindsight(
        [
            _trade("long", 100, 110),  # optimal
            _trade("long", 100, 90),  # not optimal
        ]
    )
    summary = hindsight_summary(trades)
    assert summary["num_trades"] == 2
    assert summary["num_optimal"] == 1
    assert summary["pct_optimal"] == 50.0
    assert summary["avg_regret_pct"] > 0
    assert summary["total_missed_pnl_amount"] > 0


def test_hindsight_summary_100pct_optimal_when_all_trades_were_best_possible():
    trades = annotate_trade_hindsight([_trade("long", 100, 110), _trade("short", 100, 90)])
    summary = hindsight_summary(trades)
    assert summary["pct_optimal"] == 100.0
    assert summary["avg_regret_pct"] == 0.0
    assert summary["total_missed_pnl_amount"] == 0.0
