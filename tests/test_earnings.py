from datetime import date

import pytest

import app.fundamentals.earnings as earnings_module
from app.data.finnhub_client import FinnhubUnavailableError
from app.fundamentals.earnings import (
    apply_earnings_overlay,
    earnings_report,
    earnings_tilt,
    next_earnings_date,
    summarize_surprises,
)

CONSISTENT_BEATS = [
    {"period": "2023-06-30", "actual": 1.2, "estimate": 1.0, "surprisePercent": 20.0},
    {"period": "2023-09-30", "actual": 1.3, "estimate": 1.1, "surprisePercent": 18.0},
    {"period": "2023-12-31", "actual": 1.4, "estimate": 1.25, "surprisePercent": 12.0},
    {"period": "2024-03-31", "actual": None, "estimate": 1.3, "surprisePercent": None},  # not yet reported
]

CONSISTENT_MISSES = [
    {"period": "2023-06-30", "actual": 0.9, "estimate": 1.0, "surprisePercent": -10.0},
    {"period": "2023-09-30", "actual": 0.8, "estimate": 1.0, "surprisePercent": -20.0},
    {"period": "2023-12-31", "actual": 0.85, "estimate": 1.0, "surprisePercent": -15.0},
]

MIXED = [
    {"period": "2023-06-30", "actual": 1.1, "estimate": 1.0, "surprisePercent": 10.0},
    {"period": "2023-09-30", "actual": 0.9, "estimate": 1.0, "surprisePercent": -10.0},
]


def test_summarize_surprises_ignores_unreported_quarters():
    summary = summarize_surprises(CONSISTENT_BEATS)
    assert summary["num_reports"] == 3
    assert summary["most_recent_period"] == "2023-12-31"


def test_summarize_surprises_computes_beat_rate_and_avg():
    summary = summarize_surprises(CONSISTENT_BEATS)
    assert summary["beat_rate_pct"] == 100.0
    assert summary["avg_surprise_pct"] == pytest.approx((20.0 + 18.0 + 12.0) / 3, abs=0.01)
    assert summary["most_recent_surprise_pct"] == 12.0


def test_summarize_surprises_handles_empty_list():
    summary = summarize_surprises([])
    assert summary["num_reports"] == 0
    assert summary["beat_rate_pct"] is None
    assert summary["avg_surprise_pct"] is None


def test_earnings_tilt_bullish_on_consistent_beats():
    tilt = earnings_tilt(summarize_surprises(CONSISTENT_BEATS))
    assert tilt["signal"] == "bullish"
    assert tilt["confidence_tilt_pct"] > 0


def test_earnings_tilt_bearish_on_consistent_misses():
    tilt = earnings_tilt(summarize_surprises(CONSISTENT_MISSES))
    assert tilt["signal"] == "bearish"
    assert tilt["confidence_tilt_pct"] > 0


def test_earnings_tilt_neutral_on_mixed_history():
    tilt = earnings_tilt(summarize_surprises(MIXED))
    assert tilt["signal"] == "neutral"
    assert tilt["confidence_tilt_pct"] == 0.0


def test_earnings_tilt_neutral_with_no_reports():
    tilt = earnings_tilt(summarize_surprises([]))
    assert tilt["signal"] == "neutral"
    assert tilt["confidence_tilt_pct"] == 0.0


def test_earnings_tilt_caps_at_max_tilt():
    huge_beats = [{"period": f"202{i}-01-01", "actual": 5.0, "estimate": 1.0, "surprisePercent": 400.0} for i in range(3)]
    tilt = earnings_tilt(summarize_surprises(huge_beats))
    assert tilt["confidence_tilt_pct"] == earnings_module.MAX_CONFIDENCE_TILT_PCT


def test_next_earnings_date_picks_earliest_future_date():
    today = date(2026, 7, 29)
    entries = [{"date": "2026-07-01"}, {"date": "2026-08-15"}, {"date": "2026-08-01"}]
    assert next_earnings_date(entries, today) == "2026-08-01"


def test_next_earnings_date_none_when_all_in_past():
    today = date(2026, 7, 29)
    entries = [{"date": "2026-01-01"}]
    assert next_earnings_date(entries, today) is None


def test_earnings_report_end_to_end(monkeypatch):
    monkeypatch.setattr(earnings_module, "get_earnings_surprises", lambda symbol, api_key=None: CONSISTENT_BEATS)
    monkeypatch.setattr(
        earnings_module,
        "get_earnings_calendar",
        lambda symbol, from_date, to_date, api_key=None: [{"date": "2026-08-05"}],
    )
    report = earnings_report("AAPL", today=date(2026, 7, 29))
    assert report["signal"] == "bullish"
    assert report["next_earnings_date"] == "2026-08-05"
    assert report["near_earnings"] is True


def test_apply_earnings_overlay_boosts_confidence_when_aligned(monkeypatch):
    monkeypatch.setattr(earnings_module, "get_earnings_surprises", lambda symbol, api_key=None: CONSISTENT_BEATS)
    monkeypatch.setattr(
        earnings_module,
        "get_earnings_calendar",
        lambda symbol, from_date, to_date, api_key=None: [{"date": "2026-08-05"}],
    )
    recommendation = {"overall_action": "BUY", "confidence_pct": 50.0}
    result = apply_earnings_overlay(recommendation, "AAPL", today=date(2026, 7, 29))
    assert result["confidence_pct"] > 50.0
    assert result["earnings"]["available"] is True
    assert result["earnings"]["alignment_with_technical_signal"] == "refuerza"


def test_apply_earnings_overlay_reduces_confidence_when_conflicting(monkeypatch):
    monkeypatch.setattr(earnings_module, "get_earnings_surprises", lambda symbol, api_key=None: CONSISTENT_MISSES)
    monkeypatch.setattr(
        earnings_module,
        "get_earnings_calendar",
        lambda symbol, from_date, to_date, api_key=None: [{"date": "2026-08-05"}],
    )
    recommendation = {"overall_action": "BUY", "confidence_pct": 50.0}
    result = apply_earnings_overlay(recommendation, "AAPL", today=date(2026, 7, 29))
    assert result["confidence_pct"] < 50.0
    assert result["earnings"]["alignment_with_technical_signal"] == "contradice"


def test_apply_earnings_overlay_no_adjustment_when_not_near_earnings(monkeypatch):
    monkeypatch.setattr(earnings_module, "get_earnings_surprises", lambda symbol, api_key=None: CONSISTENT_BEATS)
    monkeypatch.setattr(earnings_module, "get_earnings_calendar", lambda symbol, from_date, to_date, api_key=None: [])
    recommendation = {"overall_action": "BUY", "confidence_pct": 50.0}
    result = apply_earnings_overlay(recommendation, "AAPL", today=date(2026, 7, 29))
    assert result["confidence_pct"] == 50.0
    assert result["earnings"]["near_earnings"] is False


def test_apply_earnings_overlay_degrades_gracefully_when_finnhub_unavailable(monkeypatch):
    def raise_unavailable(symbol, api_key=None):
        raise FinnhubUnavailableError("sin API key")

    monkeypatch.setattr(earnings_module, "get_earnings_surprises", raise_unavailable)
    recommendation = {"overall_action": "BUY", "confidence_pct": 50.0}
    result = apply_earnings_overlay(recommendation, "AAPL")
    assert result["confidence_pct"] == 50.0
    assert result["earnings"]["available"] is False
