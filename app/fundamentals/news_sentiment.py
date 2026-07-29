"""News-sentiment overlay: nudges the technical ensemble recommendation using
Alpha Vantage's per-article, per-ticker sentiment scores — the general
"market mood" signal, as opposed to `app.fundamentals.earnings`'s
company-specific earnings-surprise history.

Same design as the earnings overlay: never changes what the technical
ensemble decided (BUY/SELL/HOLD), only nudges its confidence, and only when
there's enough recent, sufficiently-relevant news to trust the signal —
requiring both a minimum article count and a majority in one direction
avoids overreacting to a single noisy headline.
"""

from __future__ import annotations

from app.data.alphavantage_client import AlphaVantageUnavailableError, get_news_sentiment

MIN_RELEVANCE_SCORE = 0.15
MIN_ARTICLES_TO_TRUST = 3
STRONG_BULLISH_SCORE = 0.15
STRONG_BEARISH_SCORE = -0.15
MAX_CONFIDENCE_TILT_PCT = 15.0


def _ticker_sentiment(article: dict, symbol: str) -> dict | None:
    for entry in article.get("ticker_sentiment", []):
        if entry.get("ticker", "").upper() == symbol.upper():
            return entry
    return None


def summarize_news_sentiment(feed: list[dict], symbol: str) -> dict:
    """Reduces raw Alpha Vantage news-feed articles to a small summary,
    considering only articles relevant enough to `symbol` (relevance_score
    >= MIN_RELEVANCE_SCORE) — an article about a different company that
    mentions this symbol in passing shouldn't move its signal."""
    relevant = []
    for article in feed:
        ticker_info = _ticker_sentiment(article, symbol)
        if ticker_info is None:
            continue
        try:
            relevance = float(ticker_info.get("relevance_score", 0.0))
            score = float(ticker_info.get("ticker_sentiment_score", 0.0))
        except (TypeError, ValueError):
            continue
        if relevance < MIN_RELEVANCE_SCORE:
            continue
        relevant.append(
            {
                "title": article.get("title"),
                "time_published": article.get("time_published") or "",
                "source": article.get("source"),
                "relevance_score": relevance,
                "sentiment_score": score,
                "sentiment_label": ticker_info.get("ticker_sentiment_label"),
            }
        )

    if not relevant:
        return {
            "num_articles": 0,
            "avg_sentiment_score": None,
            "bullish_count": 0,
            "bearish_count": 0,
            "neutral_count": 0,
            "most_recent_headline": None,
            "most_recent_sentiment_score": None,
        }

    relevant.sort(key=lambda a: a["time_published"], reverse=True)
    scores = [a["sentiment_score"] for a in relevant]
    bullish = sum(1 for s in scores if s >= STRONG_BULLISH_SCORE)
    bearish = sum(1 for s in scores if s <= STRONG_BEARISH_SCORE)
    most_recent = relevant[0]
    return {
        "num_articles": len(relevant),
        "avg_sentiment_score": round(sum(scores) / len(scores), 3),
        "bullish_count": bullish,
        "bearish_count": bearish,
        "neutral_count": len(relevant) - bullish - bearish,
        "most_recent_headline": most_recent["title"],
        "most_recent_sentiment_score": most_recent["sentiment_score"],
    }


def news_tilt(summary: dict) -> dict:
    """Turns a news-sentiment summary into a signal + confidence tilt."""
    if summary["num_articles"] < MIN_ARTICLES_TO_TRUST:
        return {
            "signal": "neutral",
            "confidence_tilt_pct": 0.0,
            "rationale": (
                f"Solo {summary['num_articles']} artículo(s) relevante(s) reciente(s) — "
                f"insuficiente para ajustar la confianza (mínimo {MIN_ARTICLES_TO_TRUST})."
            ),
        }

    avg_score = summary["avg_sentiment_score"]
    bullish_majority = summary["bullish_count"] > summary["num_articles"] / 2
    bearish_majority = summary["bearish_count"] > summary["num_articles"] / 2

    if avg_score >= STRONG_BULLISH_SCORE and bullish_majority:
        signal = "bullish"
    elif avg_score <= STRONG_BEARISH_SCORE and bearish_majority:
        signal = "bearish"
    else:
        signal = "neutral"

    tilt_pct = 0.0 if signal == "neutral" else round(min(abs(avg_score) * 40, MAX_CONFIDENCE_TILT_PCT), 1)
    rationale = (
        f"{summary['bullish_count']} de {summary['num_articles']} artículos recientes con tono "
        f"positivo, {summary['bearish_count']} negativos (score promedio {avg_score:+.2f})."
    )
    return {"signal": signal, "confidence_tilt_pct": tilt_pct, "rationale": rationale}


def news_report(symbol: str, api_key: str | None = None, limit: int = 50) -> dict:
    """Fetches Alpha Vantage's recent news for `symbol` and reduces it to a
    summary + signal. Raises AlphaVantageUnavailableError if the news feed
    itself can't be fetched (missing/invalid API key, network error, rate
    limit, bad symbol)."""
    feed = get_news_sentiment(symbol, limit=limit, api_key=api_key)
    summary = summarize_news_sentiment(feed, symbol)
    tilt = news_tilt(summary)
    return {
        "symbol": symbol,
        "summary": summary,
        "signal": tilt["signal"],
        "confidence_tilt_pct": tilt["confidence_tilt_pct"],
        "rationale": tilt["rationale"],
    }


def apply_news_overlay(recommendation: dict, symbol: str, api_key: str | None = None, limit: int = 50) -> dict:
    """Adds a "news" section to a technical recommendation dict, and nudges
    confidence_pct when there's enough relevant recent news and its sentiment
    agrees or conflicts with the technical call. Degrades gracefully —
    returns the recommendation unchanged (plus an "available": false note)
    when Alpha Vantage isn't reachable or ALPHAVANTAGE_API_KEY isn't
    configured."""
    result = dict(recommendation)

    try:
        report = news_report(symbol, api_key=api_key, limit=limit)
    except AlphaVantageUnavailableError as exc:
        result["news"] = {"available": False, "reason": str(exc)}
        return result

    overall_action = result.get("overall_action")
    adjustment = 0.0
    alignment = "neutral"
    if report["signal"] != "neutral":
        agrees = (report["signal"] == "bullish" and overall_action == "BUY") or (
            report["signal"] == "bearish" and overall_action == "SELL"
        )
        conflicts = (report["signal"] == "bullish" and overall_action == "SELL") or (
            report["signal"] == "bearish" and overall_action == "BUY"
        )
        if agrees:
            adjustment = report["confidence_tilt_pct"]
            alignment = "refuerza"
        elif conflicts:
            adjustment = -report["confidence_tilt_pct"]
            alignment = "contradice"
        result["confidence_pct"] = round(min(max(result.get("confidence_pct", 0.0) + adjustment, 1.0), 99.0), 1)

    result["news"] = {
        "available": True,
        "summary": report["summary"],
        "signal": report["signal"],
        "rationale": report["rationale"],
        "confidence_adjustment_pct": round(adjustment, 1),
        "alignment_with_technical_signal": alignment,
    }
    return result
