"""Earnings-surprise overlay: nudges the technical ensemble recommendation
using the historical track record of "did this company beat/miss analyst
estimates" plus whether an earnings report is coming up soon. This is the
"expectation of a good/bad report" signal, expressed as hard historical
numbers (Finnhub's EPS surprise history) rather than NLP news sentiment.

Deliberately does not change what the technical ensemble decides (BUY/SELL/
HOLD stays whatever `recommend()` computed) — it only nudges the confidence
of that call up or down, and only when there's an earnings date within the
lookahead window, so it stays a well-scoped, explainable adjustment rather
than a second opinion that silently overrides the first.
"""

from __future__ import annotations

from datetime import date, timedelta

from app.data.finnhub_client import FinnhubUnavailableError, get_earnings_calendar, get_earnings_surprises

STRONG_BEAT_RATE_PCT = 65.0
STRONG_MISS_RATE_PCT = 35.0
MAX_CONFIDENCE_TILT_PCT = 15.0


def summarize_surprises(surprises: list[dict]) -> dict:
    """Reduces raw Finnhub earnings-surprise records to a small summary.
    Ignores quarters that haven't been reported yet (actual is None)."""
    reported = [
        s for s in surprises if s.get("actual") is not None and s.get("surprisePercent") is not None
    ]
    reported.sort(key=lambda s: s["period"])

    if not reported:
        return {
            "num_reports": 0,
            "beat_rate_pct": None,
            "avg_surprise_pct": None,
            "most_recent_period": None,
            "most_recent_surprise_pct": None,
        }

    beats = sum(1 for s in reported if s["surprisePercent"] > 0)
    most_recent = reported[-1]
    return {
        "num_reports": len(reported),
        "beat_rate_pct": round(beats / len(reported) * 100, 1),
        "avg_surprise_pct": round(sum(s["surprisePercent"] for s in reported) / len(reported), 2),
        "most_recent_period": most_recent["period"],
        "most_recent_surprise_pct": round(most_recent["surprisePercent"], 2),
    }


def earnings_tilt(summary: dict) -> dict:
    """Turns a surprise-history summary into a signal + confidence tilt.
    Requires a consistent (not just lucky-once) track record in one direction
    before calling it bullish/bearish."""
    if summary["num_reports"] == 0:
        return {
            "signal": "neutral",
            "confidence_tilt_pct": 0.0,
            "rationale": "Sin historial de reportes de resultados disponible para este símbolo.",
        }

    beat_rate = summary["beat_rate_pct"]
    avg_surprise = summary["avg_surprise_pct"]
    if beat_rate >= STRONG_BEAT_RATE_PCT and avg_surprise > 0:
        signal = "bullish"
    elif beat_rate <= STRONG_MISS_RATE_PCT and avg_surprise < 0:
        signal = "bearish"
    else:
        signal = "neutral"

    tilt_pct = 0.0 if signal == "neutral" else round(min(abs(avg_surprise) * 1.5, MAX_CONFIDENCE_TILT_PCT), 1)
    rationale = (
        f"Superó estimados de analistas en {beat_rate:.0f}% de los últimos {summary['num_reports']} "
        f"reportes (sorpresa promedio {avg_surprise:+.2f}%)."
    )
    return {"signal": signal, "confidence_tilt_pct": tilt_pct, "rationale": rationale}


def next_earnings_date(calendar_entries: list[dict], today: date) -> str | None:
    upcoming = sorted(
        e["date"] for e in calendar_entries if e.get("date") and date.fromisoformat(e["date"]) >= today
    )
    return upcoming[0] if upcoming else None


def earnings_report(
    symbol: str,
    api_key: str | None = None,
    near_window_days: int = 14,
    today: date | None = None,
) -> dict:
    """Fetches Finnhub's earnings-surprise history for `symbol` and reduces
    it to a summary, a signal, and (best-effort) the next scheduled earnings
    date. Raises FinnhubUnavailableError if the surprise history itself
    can't be fetched (missing/invalid API key, network error, bad symbol);
    the calendar lookup is best-effort and silently omitted on failure since
    it's a secondary, less-reliable piece of the picture."""
    today = today or date.today()
    surprises = get_earnings_surprises(symbol, api_key=api_key)
    summary = summarize_surprises(surprises)
    tilt = earnings_tilt(summary)

    next_date = None
    try:
        calendar_entries = get_earnings_calendar(
            symbol, today.isoformat(), (today + timedelta(days=near_window_days)).isoformat(), api_key=api_key
        )
        next_date = next_earnings_date(calendar_entries, today)
    except FinnhubUnavailableError:
        pass  # the calendar is best-effort; the surprise history alone is still useful

    return {
        "symbol": symbol,
        "summary": summary,
        "signal": tilt["signal"],
        "confidence_tilt_pct": tilt["confidence_tilt_pct"],
        "rationale": tilt["rationale"],
        "next_earnings_date": next_date,
        "near_earnings": next_date is not None,
    }


def apply_earnings_overlay(
    recommendation: dict,
    symbol: str,
    api_key: str | None = None,
    near_window_days: int = 14,
    today: date | None = None,
) -> dict:
    """Adds an "earnings" section to a technical recommendation dict, and
    nudges its confidence_pct when there's an earnings report due within
    `near_window_days` and the historical-surprise signal agrees or
    conflicts with the technical call. Degrades gracefully — returns the
    recommendation unchanged (plus an "available": false note) when Finnhub
    isn't reachable or FINNHUB_API_KEY isn't configured."""
    result = dict(recommendation)

    try:
        report = earnings_report(symbol, api_key=api_key, near_window_days=near_window_days, today=today)
    except FinnhubUnavailableError as exc:
        result["earnings"] = {"available": False, "reason": str(exc)}
        return result

    overall_action = result.get("overall_action")
    adjustment = 0.0
    alignment = "neutral"
    if report["near_earnings"] and report["signal"] != "neutral":
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

    result["earnings"] = {
        "available": True,
        "summary": report["summary"],
        "signal": report["signal"],
        "rationale": report["rationale"],
        "next_earnings_date": report["next_earnings_date"],
        "near_earnings": report["near_earnings"],
        "confidence_adjustment_pct": round(adjustment, 1),
        "alignment_with_technical_signal": alignment,
    }
    return result
