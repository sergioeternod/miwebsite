"""Sector/industry-relative P/E reading: "cheap" means cheap FOR WHAT IT IS.

A P/E of 27 is unremarkable for infrastructure software and wildly
expensive for an auto manufacturer — the generic 15/30 bands can't see
that. This module compares a stock's trailing P/E against a fixed
reference median for its industry (falling back to its sector), and reads
the RATIO: below 0.8x the reference is cheap-for-its-industry, above 1.2x
is expensive-for-its-industry, in between is in line.

Honesty rules:

- The reference medians are long-run, round-number approximations in the
  spirit of public industry-average datasets (e.g. Damodaran's NYU
  tables). They are deliberately coarse, fixed in this file, documented,
  and NOT fitted to any backtest — editing them is a code change with a
  diff, not a knob. If an industry is missing, the sector fallback
  applies; if both are missing, the reading is "sin referencia" and no
  verdict is produced.
- The 0.8x / 1.2x thresholds are fixed and symmetric.
- This reading is informational (dashboard) — it does not feed the model.
  Making it a model input would require the same point-in-time treatment
  and 9-window validation as everything else.
"""

from __future__ import annotations

from app.config import AssetClass, infer_asset_class
from app.data.yahoo_quote_client import QuoteSummaryUnavailableError, get_asset_profile

# Referencias aproximadas de mediana de P/E de largo plazo por industria
# (claves = nombres de industria de Yahoo Finance).
INDUSTRY_MEDIAN_PE = {
    "Software - Infrastructure": 30.0,
    "Software - Application": 32.0,
    "Semiconductors": 28.0,
    "Semiconductor Equipment & Materials": 25.0,
    "Consumer Electronics": 25.0,
    "Internet Retail": 32.0,
    "Internet Content & Information": 26.0,
    "Auto Manufacturers": 12.0,
    "Banks - Diversified": 11.0,
    "Drug Manufacturers - General": 18.0,
    "Oil & Gas Integrated": 11.0,
    "Aerospace & Defense": 22.0,
}

# Fallback por sector cuando la industria no está en la tabla.
SECTOR_MEDIAN_PE = {
    "Technology": 27.0,
    "Communication Services": 20.0,
    "Consumer Cyclical": 22.0,
    "Consumer Defensive": 21.0,
    "Healthcare": 21.0,
    "Financial Services": 14.0,
    "Energy": 12.0,
    "Utilities": 18.0,
    "Industrials": 20.0,
    "Basic Materials": 14.0,
    "Real Estate": 30.0,
}

CHEAP_RATIO_MAX = 0.8
EXPENSIVE_RATIO_MIN = 1.2


def reference_pe_for(sector: str | None, industry: str | None) -> tuple[float | None, str | None]:
    """(median, label) — industry table first, sector fallback second."""
    if industry and industry in INDUSTRY_MEDIAN_PE:
        return INDUSTRY_MEDIAN_PE[industry], industry
    if sector and sector in SECTOR_MEDIAN_PE:
        return SECTOR_MEDIAN_PE[sector], sector
    return None, None


def relative_reading(trailing_pe: float | None, reference_pe: float | None) -> dict:
    """The ratio verdict with fixed symmetric thresholds."""
    if trailing_pe is None or trailing_pe <= 0 or not reference_pe:
        return {"ratio": None, "reading": "sin referencia"}
    ratio = round(trailing_pe / reference_pe, 2)
    if ratio < CHEAP_RATIO_MAX:
        reading = "barata para su industria"
    elif ratio > EXPENSIVE_RATIO_MIN:
        reading = "cara para su industria"
    else:
        reading = "en línea con su industria"
    return {"ratio": ratio, "reading": reading}


def sector_relative_valuation(symbol: str, trailing_pe: float | None) -> dict:
    """Full sector-relative report for a stock. Degrades to
    'sin referencia' on any data failure; non-stocks are not applicable."""
    if infer_asset_class(symbol) is not AssetClass.STOCK:
        return {"applicable": False}
    try:
        profile = get_asset_profile(symbol)
    except QuoteSummaryUnavailableError:
        return {"applicable": True, "sector": None, "industry": None, "reference_pe": None,
                "reference_label": None, "ratio": None, "reading": "sin referencia"}
    reference, label = reference_pe_for(profile.get("sector"), profile.get("industry"))
    verdict = relative_reading(trailing_pe, reference)
    return {
        "applicable": True,
        "sector": profile.get("sector"),
        "industry": profile.get("industry"),
        "reference_pe": reference,
        "reference_label": label,
        "ratio": verdict["ratio"],
        "reading": verdict["reading"],
    }
