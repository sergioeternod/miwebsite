"""Point-in-time historical P/E (SEC EDGAR) — the validatable half of the
valuation signal.

The live overlay (app.fundamentals.valuation) is now-only by construction:
Yahoo reports today's multiple. This module reconstructs the multiple as it
looked ON ANY PAST DATE — price on that date divided by the trailing EPS
whose filings were already public that day (see
app.data.edgar_client.trailing_eps_known_at). No lookahead: a 10-Q filed in
August cannot influence a July decision.

That causality is what lets the P/E tilt participate in the *model itself*
(portfolio selection) and be judged on the historical windows like every
other adopted piece — instead of living forever as an unvalidatable
overlay. It reuses the exact fixed bands from the live overlay
(valuation_tilt): one rulebook for both the live and historical readings.
"""

from __future__ import annotations

import pandas as pd

import json
import urllib.parse
import urllib.request

from app.config import AssetClass, infer_asset_class
from app.data.edgar_client import EdgarUnavailableError, get_quarterly_eps, trailing_eps_known_at
from app.fundamentals.valuation import valuation_tilt

# Split adjustment: the model's price series is split-adjusted through
# today, while EDGAR EPS is filed in the share count of its own era —
# dividing one by the other across a split boundary produces nonsense
# (AAPL's 2020 4:1 split alone would misstate its 2019 P/E by 4x). Each
# quarter's EPS is therefore divided by the product of split ratios that
# happened AFTER its period end; both sides of the P/E then share today's
# share units and the factors cancel, so no future information leaks into
# the ratio. Residual honesty note: Yahoo's adjusted closes also fold in
# dividends, which biases reconstructed historical P/Es slightly LOW
# (by roughly the cumulative dividend yield since the date) — a uniform,
# documented distortion, not a tunable knob.
_SPLITS_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range=max&interval=1d&events=splits"
_SPLITS_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
_splits_cache: dict[str, list[dict]] = {}
_adjusted_cache: dict[str, list[dict]] = {}


def get_split_events(symbol: str) -> list[dict]:
    """[{'date': 'YYYY-MM-DD', 'ratio': float}] for every split in the
    symbol's history (Yahoo chart events, keyless), cached in-process.
    Failures return [] — better an unadjusted-but-flagged read upstream
    than a crash here; callers treat missing splits as 'none known'."""
    cached = _splits_cache.get(symbol.upper())
    if cached is not None:
        return cached
    try:
        req = urllib.request.Request(_SPLITS_URL.format(symbol=urllib.parse.quote(symbol)), headers=_SPLITS_UA)
        with urllib.request.urlopen(req, timeout=20) as response:
            payload = json.loads(response.read())
        raw = ((payload["chart"]["result"][0].get("events") or {}).get("splits") or {})
        from datetime import datetime, timezone

        events = sorted(
            (
                {
                    "date": datetime.fromtimestamp(int(e["date"]), tz=timezone.utc).date().isoformat(),
                    "ratio": float(e["numerator"]) / float(e["denominator"]),
                }
                for e in raw.values()
                if float(e.get("denominator") or 0) != 0
            ),
            key=lambda e: e["date"],
        )
    except Exception:
        events = []
    _splits_cache[symbol.upper()] = events
    return events


def _split_adjusted_quarters(symbol: str) -> list[dict]:
    """EDGAR quarters with each EPS divided by the split ratios that came
    after its period end — i.e., restated into today's share units, the
    same units the adjusted price series uses."""
    cached = _adjusted_cache.get(symbol.upper())
    if cached is not None:
        return cached
    quarters = get_quarterly_eps(symbol)
    splits = get_split_events(symbol)
    adjusted = []
    for q in quarters:
        factor = 1.0
        for s in splits:
            if s["date"] > q["end"]:
                factor *= s["ratio"]
        adjusted.append({**q, "eps": q["eps"] / factor})
    _adjusted_cache[symbol.upper()] = adjusted
    return adjusted


def pe_known_at(symbol: str, price: float, as_of: str) -> float | None:
    """Trailing P/E for `symbol` as it was knowable on `as_of` (ISO date),
    using EDGAR filings public by that date. None when not a stock, EDGAR
    lacks data, or trailing EPS is non-positive."""
    if infer_asset_class(symbol) is not AssetClass.STOCK:
        return None
    try:
        quarters = _split_adjusted_quarters(symbol)
    except EdgarUnavailableError:
        return None
    eps = trailing_eps_known_at(quarters, as_of)
    if eps is None or eps <= 0:
        return None
    return round(price / eps, 2)


def apply_pe_history_tilt(recommendation: dict, symbol: str, window: pd.DataFrame) -> dict:
    """Selection-time counterpart of apply_valuation_overlay, driven by
    point-in-time data: nudges the recommendation's confidence with the
    fixed P/E bands, computed strictly from what was public at the window's
    last date. Non-stocks, missing EDGAR data or neutral readings leave the
    recommendation untouched (plus a small note). Same contract as every
    overlay: the technical action never changes."""
    result = dict(recommendation)
    as_of = str(window.index[-1].date())
    pe = pe_known_at(symbol, float(window["Close"].iloc[-1]), as_of)
    if pe is None:
        result["pe_history"] = {"applicable": False, "as_of": as_of}
        return result

    tilt = valuation_tilt(pe, None)
    overall_action = result.get("overall_action")
    adjustment = 0.0
    alignment = "neutral"
    if tilt["signal"] != "neutral":
        agrees = (tilt["signal"] == "bullish" and overall_action == "BUY") or (
            tilt["signal"] == "bearish" and overall_action == "SELL"
        )
        conflicts = (tilt["signal"] == "bullish" and overall_action == "SELL") or (
            tilt["signal"] == "bearish" and overall_action == "BUY"
        )
        if agrees:
            adjustment = tilt["confidence_tilt_pct"]
            alignment = "refuerza"
        elif conflicts:
            adjustment = -tilt["confidence_tilt_pct"]
            alignment = "contradice"
        result["confidence_pct"] = round(min(max(result.get("confidence_pct", 0.0) + adjustment, 1.0), 99.0), 1)

    result["pe_history"] = {
        "applicable": True,
        "as_of": as_of,
        "trailing_pe": pe,
        "signal": tilt["signal"],
        "confidence_adjustment_pct": round(adjustment, 1),
        "alignment_with_technical_signal": alignment,
    }
    return result
