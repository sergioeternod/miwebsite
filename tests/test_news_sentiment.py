import pytest

import app.fundamentals.news_sentiment as news_module
from app.data.alphavantage_client import AlphaVantageUnavailableError
from app.fundamentals.news_sentiment import (
    apply_news_overlay,
    news_report,
    news_tilt,
    summarize_news_sentiment,
)


def _article(symbol="AAPL", relevance="0.9", score="0.3", label="Somewhat-Bullish", time="20260729T130000", title="Headline"):
    return {
        "title": title,
        "time_published": time,
        "source": "Reuters",
        "ticker_sentiment": [
            {"ticker": symbol, "relevance_score": relevance, "ticker_sentiment_score": score, "ticker_sentiment_label": label}
        ],
    }


BULLISH_FEED = [
    _article(score="0.30", time="20260729T130000", title="Beats estimates"),
    _article(score="0.25", time="20260728T090000", title="Strong guidance"),
    _article(score="0.35", time="20260727T090000", title="Analyst upgrade"),
]

BEARISH_FEED = [
    _article(score="-0.30", time="20260729T130000", title="Misses estimates"),
    _article(score="-0.25", time="20260728T090000", title="Weak guidance"),
    _article(score="-0.20", time="20260727T090000", title="Analyst downgrade"),
]

MIXED_FEED = [
    _article(score="0.30", time="20260729T130000", title="Good news"),
    _article(score="-0.30", time="20260728T090000", title="Bad news"),
    _article(score="0.10", time="20260727T090000", title="Neutral news"),
]

LOW_RELEVANCE_FEED = [_article(relevance="0.05", score="0.5", title="Barely mentions AAPL")]


def test_summarize_news_sentiment_filters_by_relevance():
    summary = summarize_news_sentiment(LOW_RELEVANCE_FEED, "AAPL")
    assert summary["num_articles"] == 0


def test_summarize_news_sentiment_ignores_other_symbols():
    feed = [_article(symbol="MSFT")]
    summary = summarize_news_sentiment(feed, "AAPL")
    assert summary["num_articles"] == 0


def test_summarize_news_sentiment_computes_counts_and_avg():
    summary = summarize_news_sentiment(BULLISH_FEED, "AAPL")
    assert summary["num_articles"] == 3
    assert summary["bullish_count"] == 3
    assert summary["bearish_count"] == 0
    assert summary["avg_sentiment_score"] == pytest.approx((0.30 + 0.25 + 0.35) / 3, abs=0.001)


def test_summarize_news_sentiment_most_recent_by_time_published():
    summary = summarize_news_sentiment(BULLISH_FEED, "AAPL")
    assert summary["most_recent_headline"] == "Beats estimates"


def test_summarize_news_sentiment_empty_feed():
    summary = summarize_news_sentiment([], "AAPL")
    assert summary["num_articles"] == 0
    assert summary["avg_sentiment_score"] is None


def test_news_tilt_bullish_on_consistent_positive_coverage():
    tilt = news_tilt(summarize_news_sentiment(BULLISH_FEED, "AAPL"))
    assert tilt["signal"] == "bullish"
    assert tilt["confidence_tilt_pct"] > 0


def test_news_tilt_bearish_on_consistent_negative_coverage():
    tilt = news_tilt(summarize_news_sentiment(BEARISH_FEED, "AAPL"))
    assert tilt["signal"] == "bearish"
    assert tilt["confidence_tilt_pct"] > 0


def test_news_tilt_neutral_on_mixed_coverage():
    tilt = news_tilt(summarize_news_sentiment(MIXED_FEED, "AAPL"))
    assert tilt["signal"] == "neutral"
    assert tilt["confidence_tilt_pct"] == 0.0


def test_news_tilt_neutral_below_min_article_count():
    two_articles = BULLISH_FEED[:2]
    tilt = news_tilt(summarize_news_sentiment(two_articles, "AAPL"))
    assert tilt["signal"] == "neutral"
    assert tilt["confidence_tilt_pct"] == 0.0


def test_news_tilt_caps_at_max_tilt():
    huge_bullish = [_article(score="0.9", time=f"2026072{i}T090000") for i in range(3)]
    tilt = news_tilt(summarize_news_sentiment(huge_bullish, "AAPL"))
    assert tilt["confidence_tilt_pct"] == news_module.MAX_CONFIDENCE_TILT_PCT


def test_news_report_end_to_end(monkeypatch):
    monkeypatch.setattr(news_module, "get_news_sentiment", lambda symbol, limit=50, api_key=None: BULLISH_FEED)
    report = news_report("AAPL")
    assert report["signal"] == "bullish"
    assert report["summary"]["num_articles"] == 3


def test_apply_news_overlay_boosts_confidence_when_aligned(monkeypatch):
    monkeypatch.setattr(news_module, "get_news_sentiment", lambda symbol, limit=50, api_key=None: BULLISH_FEED)
    recommendation = {"overall_action": "BUY", "confidence_pct": 50.0}
    result = apply_news_overlay(recommendation, "AAPL")
    assert result["confidence_pct"] > 50.0
    assert result["news"]["available"] is True
    assert result["news"]["alignment_with_technical_signal"] == "refuerza"


def test_apply_news_overlay_reduces_confidence_when_conflicting(monkeypatch):
    monkeypatch.setattr(news_module, "get_news_sentiment", lambda symbol, limit=50, api_key=None: BEARISH_FEED)
    recommendation = {"overall_action": "BUY", "confidence_pct": 50.0}
    result = apply_news_overlay(recommendation, "AAPL")
    assert result["confidence_pct"] < 50.0
    assert result["news"]["alignment_with_technical_signal"] == "contradice"


def test_apply_news_overlay_no_adjustment_when_mixed(monkeypatch):
    monkeypatch.setattr(news_module, "get_news_sentiment", lambda symbol, limit=50, api_key=None: MIXED_FEED)
    recommendation = {"overall_action": "BUY", "confidence_pct": 50.0}
    result = apply_news_overlay(recommendation, "AAPL")
    assert result["confidence_pct"] == 50.0


def test_apply_news_overlay_degrades_gracefully_when_alphavantage_unavailable(monkeypatch):
    def raise_unavailable(symbol, limit=50, api_key=None):
        raise AlphaVantageUnavailableError("sin API key")

    monkeypatch.setattr(news_module, "get_news_sentiment", raise_unavailable)
    recommendation = {"overall_action": "BUY", "confidence_pct": 50.0}
    result = apply_news_overlay(recommendation, "AAPL")
    assert result["confidence_pct"] == 50.0
    assert result["news"]["available"] is False
