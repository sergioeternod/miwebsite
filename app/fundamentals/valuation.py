"""Valuation-multiple overlay (price-to-earnings): nudges the technical
ensemble recommendation using how expensive or cheap a stock is relative to
its earnings. A high-confidence technical BUY on a stock trading at 60x
earnings carries a different risk than the same BUY at 12x — this overlay
makes that difference explicit and lets it tilt the confidence.

Same contract as the earnings/news overlays: it never changes what the
technical ensemble decided (BUY/SELL/HOLD stays), only nudges the
confidence, with the adjustment and its rationale reported alongside.

Scope and honesty rules:

- Stocks only. Indexes, crypto, forex and commodities have no meaningful
  per-symbol P/E from this source; the overlay marks itself not-applicable
  and changes nothing.
- Now-only, like earnings/news: Yahoo reports today's multiples with no
  historical "as of" parameter, so this can NEVER enter the historical
  walk-forward — it would leak today's valuation into past-dated decisions.
  It applies at recommendation/scan time only, and its live usefulness is
  judged by the forward signal log, not by backtests.
- The bands are classic rules of thumb, fixed BEFORE use and not tuned:
  P/E below 15 reads cheap; above 30 reads expensive; in between (or
  missing / negative, i.e. loss-making) the overlay stays neutral. The
  tilt grows with distance past the band edge, capped at
  MAX_CONFIDENCE_TILT_PCT.
"""

from __future__ import annotations

from app.config import AssetClass, infer_asset_class
from app.data.yahoo_quote_client import QuoteSummaryUnavailableError, get_valuation_metrics

CHEAP_PE_MAX = 15.0
EXPENSIVE_PE_MIN = 30.0
MAX_CONFIDENCE_TILT_PCT = 10.0


def valuation_tilt(trailing_pe: float | None, forward_pe: float | None) -> dict:
    """Fixed-band tilt from the trailing P/E. The forward P/E only colors
    the rationale (an expensive stock whose forward multiple is much lower
    is pricing in earnings growth); it doesn't move the tilt — one knob,
    fixed bands, nothing to tune."""
    if trailing_pe is None or trailing_pe <= 0:
        return {
            "signal": "neutral",
            "confidence_tilt_pct": 0.0,
            "rationale": "Sin P/E utilizable (sin dato o utilidades negativas) — el overlay no opina.",
        }

    if trailing_pe < CHEAP_PE_MAX:
        distance = (CHEAP_PE_MAX - trailing_pe) / CHEAP_PE_MAX
        signal = "bullish"
        reading = f"barata (P/E {trailing_pe:.1f} < {CHEAP_PE_MAX:.0f})"
    elif trailing_pe > EXPENSIVE_PE_MIN:
        distance = (trailing_pe - EXPENSIVE_PE_MIN) / EXPENSIVE_PE_MIN
        signal = "bearish"
        reading = f"cara (P/E {trailing_pe:.1f} > {EXPENSIVE_PE_MIN:.0f})"
    else:
        return {
            "signal": "neutral",
            "confidence_tilt_pct": 0.0,
            "rationale": f"Valuación razonable (P/E {trailing_pe:.1f} entre {CHEAP_PE_MAX:.0f} y {EXPENSIVE_PE_MIN:.0f}) — sin ajuste.",
        }

    tilt = round(min(distance * MAX_CONFIDENCE_TILT_PCT, MAX_CONFIDENCE_TILT_PCT), 1)
    rationale = f"Valuación {reading}."
    if forward_pe is not None and forward_pe > 0 and trailing_pe > 0:
        if forward_pe < trailing_pe * 0.85:
            rationale += f" El P/E forward ({forward_pe:.1f}) es bastante menor: el mercado espera utilidades crecientes."
        elif forward_pe > trailing_pe * 1.15:
            rationale += f" El P/E forward ({forward_pe:.1f}) es mayor: el mercado espera utilidades a la baja."
    return {"signal": signal, "confidence_tilt_pct": tilt, "rationale": rationale}


def valuation_report(symbol: str) -> dict:
    """Current valuation reading for `symbol`. Raises
    QuoteSummaryUnavailableError when Yahoo can't provide data; returns a
    not-applicable report for non-stock asset classes without fetching."""
    if infer_asset_class(symbol) is not AssetClass.STOCK:
        return {
            "symbol": symbol,
            "applicable": False,
            "signal": "neutral",
            "confidence_tilt_pct": 0.0,
            "rationale": "La valuación por múltiplos aplica solo a acciones individuales.",
        }
    metrics = get_valuation_metrics(symbol)
    tilt = valuation_tilt(metrics["trailing_pe"], metrics["forward_pe"])
    return {
        "symbol": symbol,
        "applicable": True,
        "trailing_pe": metrics["trailing_pe"],
        "forward_pe": metrics["forward_pe"],
        "trailing_eps": metrics["trailing_eps"],
        "signal": tilt["signal"],
        "confidence_tilt_pct": tilt["confidence_tilt_pct"],
        "rationale": tilt["rationale"],
    }


def apply_valuation_overlay(recommendation: dict, symbol: str) -> dict:
    """Adds a "valuation" section to a technical recommendation dict and
    nudges its confidence_pct when the P/E signal reinforces or contradicts
    the technical call (cheap reinforces BUY / contradicts SELL; expensive
    the reverse). Degrades gracefully: on any data failure the
    recommendation comes back unchanged plus an "available": false note."""
    result = dict(recommendation)

    try:
        report = valuation_report(symbol)
    except QuoteSummaryUnavailableError as exc:
        result["valuation"] = {"available": False, "reason": str(exc)}
        return result

    overall_action = result.get("overall_action")
    adjustment = 0.0
    alignment = "neutral"
    if report["applicable"] and report["signal"] != "neutral":
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

    result["valuation"] = {
        "available": True,
        "applicable": report["applicable"],
        "trailing_pe": report.get("trailing_pe"),
        "forward_pe": report.get("forward_pe"),
        "signal": report["signal"],
        "rationale": report["rationale"],
        "confidence_adjustment_pct": round(adjustment, 1),
        "alignment_with_technical_signal": alignment,
    }
    return result
