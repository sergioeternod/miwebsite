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

# Guidance proxy: analyst consensus EPS estimates and their 90-day revision
# direction (Yahoo earningsTrend). Companies guide, analysts move their
# numbers — sustained upward revisions for both this year and next are the
# closest keyless observable to "guidance is improving". Fixed thresholds,
# not tuned: revisions must move at least REVISION_STRONG_PCT in the same
# direction for both periods to count, and contribute at most
# REVISION_TILT_PCT confidence points.
REVISION_STRONG_PCT = 2.0
REVISION_TILT_PCT = 3.0


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


def guidance_tilt(estimates: dict) -> dict:
    """Revision-direction reading from consensus estimates for the current
    (0y) and next (+1y) fiscal years. Both must have moved at least
    REVISION_STRONG_PCT in the same direction over the last 90 days to
    produce a signal; anything else — including missing data — is neutral."""
    changes = []
    for period in ("0y", "+1y"):
        est = estimates.get(period) or {}
        avg, ago = est.get("eps_avg"), est.get("eps_avg_90d_ago")
        if avg is None or ago is None or ago == 0:
            return {"signal": "neutral", "confidence_tilt_pct": 0.0,
                    "rationale": "Sin estimaciones de analistas suficientes para leer revisiones."}
        changes.append((avg / ago - 1) * 100)

    if all(c >= REVISION_STRONG_PCT for c in changes):
        return {"signal": "bullish", "confidence_tilt_pct": REVISION_TILT_PCT,
                "rationale": f"Los analistas revisaron al alza sus estimados de utilidades ({changes[0]:+.1f}% este año, {changes[1]:+.1f}% el próximo, últimos 90 días)."}
    if all(c <= -REVISION_STRONG_PCT for c in changes):
        return {"signal": "bearish", "confidence_tilt_pct": REVISION_TILT_PCT,
                "rationale": f"Los analistas revisaron a la baja sus estimados de utilidades ({changes[0]:+.1f}% este año, {changes[1]:+.1f}% el próximo, últimos 90 días)."}
    return {"signal": "neutral", "confidence_tilt_pct": 0.0,
            "rationale": f"Revisiones de estimados mixtas o planas ({changes[0]:+.1f}% / {changes[1]:+.1f}% en 90 días)."}


def combine_tilts(band: dict, guidance: dict) -> dict:
    """Combines the P/E-band tilt and the guidance tilt on a signed scale
    (bullish positive, bearish negative), capping the total at
    MAX_CONFIDENCE_TILT_PCT. Opposing readings partially cancel — a cheap
    stock whose estimates are being cut is a weaker buy case than cheap
    alone, and that should show in the number."""
    signed = 0.0
    for tilt in (band, guidance):
        if tilt["signal"] == "bullish":
            signed += tilt["confidence_tilt_pct"]
        elif tilt["signal"] == "bearish":
            signed -= tilt["confidence_tilt_pct"]
    if signed == 0:
        signal = "neutral"
    else:
        signal = "bullish" if signed > 0 else "bearish"
    magnitude = round(min(abs(signed), MAX_CONFIDENCE_TILT_PCT), 1)
    rationale = " ".join(t["rationale"] for t in (band, guidance))
    return {"signal": signal, "confidence_tilt_pct": magnitude if signal != "neutral" else 0.0, "rationale": rationale}


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
    band = valuation_tilt(metrics["trailing_pe"], metrics["forward_pe"])
    guidance = guidance_tilt(metrics.get("estimates") or {})
    combined = combine_tilts(band, guidance)

    implicit_forward_pe = None
    next_year = (metrics.get("estimates") or {}).get("+1y") or {}
    if metrics.get("previous_close") and next_year.get("eps_avg"):
        if next_year["eps_avg"] > 0:
            implicit_forward_pe = round(metrics["previous_close"] / next_year["eps_avg"], 2)

    return {
        "symbol": symbol,
        "applicable": True,
        "trailing_pe": metrics["trailing_pe"],
        "forward_pe": metrics["forward_pe"],
        "implicit_forward_pe": implicit_forward_pe,
        "trailing_eps": metrics["trailing_eps"],
        "estimates": metrics.get("estimates") or {},
        "guidance_signal": guidance["signal"],
        "signal": combined["signal"],
        "confidence_tilt_pct": combined["confidence_tilt_pct"],
        "rationale": combined["rationale"],
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
        "implicit_forward_pe": report.get("implicit_forward_pe"),
        "guidance_signal": report.get("guidance_signal"),
        "signal": report["signal"],
        "rationale": report["rationale"],
        "confidence_adjustment_pct": round(adjustment, 1),
        "alignment_with_technical_signal": alignment,
    }
    return result
