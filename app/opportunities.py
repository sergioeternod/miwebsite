"""Opportunity scanner: runs the ensemble recommendation engine (optionally
overlaid with earnings/news signals) across many symbols at once, and
surfaces the ones with the strongest BUY or SELL/short signal — answering
"which symbols look most promising right now?" instead of requiring the
caller to already know which symbol to check.
"""

from __future__ import annotations

import pandas as pd

from app.config import EXAMPLE_SYMBOLS
from app.data.providers import get_ohlcv
from app.data.synthetic import generate_ohlcv
from app.fundamentals.earnings import apply_earnings_overlay
from app.fundamentals.news_sentiment import apply_news_overlay
from app.ranking import DEFAULT_SYMBOL_PROFILES
from app.recommend.engine import recommend

DISCLAIMER = (
    "Esta recomendación se basa únicamente en indicadores técnicos y backtests históricos "
    "(y, si se activaron, historial de earnings/sentimiento de noticias); no es asesoría "
    "financiera y no garantiza resultados futuros."
)


def _default_symbols() -> list[str]:
    return [entry["symbol"] for symbols in EXAMPLE_SYMBOLS.values() for entry in symbols]


def _evaluate(
    df: pd.DataFrame,
    symbol: str,
    initial_capital: float,
    commission_bps: float,
    allow_short: bool,
    include_earnings: bool,
    include_news: bool,
) -> dict:
    result = recommend(
        df, symbol=symbol, initial_capital=initial_capital, commission_bps=commission_bps, allow_short=allow_short
    )
    if include_earnings:
        result = apply_earnings_overlay(result, symbol)
    if include_news:
        result = apply_news_overlay(result, symbol)
    # per_strategy is verbose (5 entries with backtest stats each) and not
    # needed to rank/scan — callers wanting the full picture on one symbol
    # should follow up with recommend_for_symbol / GET /recommend/{symbol}.
    return {k: v for k, v in result.items() if k not in ("per_strategy", "disclaimer")}


def _build_report(entries: list[dict], errors: dict[str, str], top_n: int) -> dict:
    buy = sorted((e for e in entries if e["overall_action"] == "BUY"), key=lambda e: e["confidence_pct"], reverse=True)
    sell = sorted((e for e in entries if e["overall_action"] == "SELL"), key=lambda e: e["confidence_pct"], reverse=True)
    return {
        "evaluated": len(entries),
        "top_buy": buy[:top_n],
        "top_sell": sell[:top_n],
        "errors": errors,
        "disclaimer": DISCLAIMER,
    }


def find_opportunities_real(
    symbols: list[str] | None = None,
    period: str = "2y",
    interval: str = "1d",
    initial_capital: float = 10_000.0,
    commission_bps: float = 5.0,
    allow_short: bool = True,
    include_earnings: bool = False,
    include_news: bool = False,
    top_n: int = 5,
) -> dict:
    """Scans real symbols (defaults to the full example universe) and ranks
    them by recommendation confidence, separately for BUY and SELL/short
    candidates. Per-symbol data failures are recorded in `errors` and don't
    abort the rest of the scan."""
    symbols = symbols or _default_symbols()

    entries = []
    errors = {}
    for symbol in symbols:
        try:
            df = get_ohlcv(symbol, period=period, interval=interval)
            entries.append(
                _evaluate(df, symbol, initial_capital, commission_bps, allow_short, include_earnings, include_news)
            )
        except Exception as exc:  # data provider/network failures are per-symbol, not fatal for the whole scan
            errors[symbol] = str(exc)

    return _build_report(entries, errors, top_n)


def find_opportunities_synthetic(
    profiles: list[dict] | None = None,
    seed: int = 42,
    initial_capital: float = 10_000.0,
    commission_bps: float = 5.0,
    allow_short: bool = True,
    include_earnings: bool = False,
    include_news: bool = False,
    top_n: int = 5,
) -> dict:
    """Same ranking, but over synthetic market-character profiles — usable
    with no network access, mirroring app.ranking/app.screener's synthetic
    fallback. include_earnings/include_news still call out to Finnhub/Alpha
    Vantage for these (fake) profile labels, so they'll show up as
    unavailable without real API access, same as any other symbol."""
    profiles = profiles or DEFAULT_SYMBOL_PROFILES

    entries = [
        _evaluate(
            generate_ohlcv(regimes=profile["regimes"], seed=seed),
            profile["label"],
            initial_capital,
            commission_bps,
            allow_short,
            include_earnings,
            include_news,
        )
        for profile in profiles
    ]
    return _build_report(entries, {}, top_n)
