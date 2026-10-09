"""Pinned price-history "vintage" for the daily chart rebuilds.

Problem it solves: the published simulation charts re-run from scratch every
day over freshly downloaded history, and Yahoo silently revises adjusted
closes by fractions of a percent. Symbols sitting at the BUY>=55% cutoff on
a reselection boundary flip in or out, and a one-pick change moved the
12-month chart by ~19 pp overnight. Pinning the history makes the published
series stable day to day: only genuinely new bars are appended.

Mechanics (opt-in via MIWEB_PRICE_VINTAGE=1, daily bars + period-based
fetches only):
- data/price_vintage/<symbol>.csv holds the frozen history (committed to
  the repo so it survives container recycles — that persistence IS the fix).
- Each call fetches only a short fresh tail. The overlap with the cached
  tail is compared; if any shared close differs by more than SEAM_TOL_PCT
  (a real split/dividend re-adjustment, not noise), the symbol's whole
  history is deliberately re-fetched (a "vintage bump") and flagged in the
  returned frame's attrs and on stderr, so a jump in the charts is always
  attributable.
- Never used by the live scan/dashboard, which want fresh data.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

VINTAGE_DIR = Path(__file__).resolve().parents[2] / "data" / "price_vintage"
SEAM_TOL_PCT = 0.5
TAIL_PERIOD = "3mo"  # fresh fetch window: overlap check + new bars
BASE_PERIOD = "6y"   # span fetched on first use / vintage bump ("6y" only used here, via start-date math)
_PERIOD_DAYS = {"d": 1, "mo": 31, "y": 366}


def _period_to_days(period: str) -> int:
    m = re.fullmatch(r"(\d+)(d|mo|y)", period)
    if not m:
        raise ValueError(f"Periodo no soportado por el vintage: {period!r}")
    return int(m.group(1)) * _PERIOD_DAYS[m.group(2)]


def _cache_path(symbol: str) -> Path:
    return VINTAGE_DIR / (re.sub(r"[^A-Za-z0-9.\-]", "_", symbol) + ".csv")


def _load(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    df.index.name = "Date"
    return df


def _save(path: Path, df: pd.DataFrame) -> None:
    VINTAGE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(path)


def _full_fetch(symbol: str, fetch) -> pd.DataFrame:
    start = (pd.Timestamp.today().normalize() - pd.DateOffset(days=_period_to_days(BASE_PERIOD))).date().isoformat()
    return fetch(symbol, None, "1d", start, None)


def pinned_ohlcv(symbol: str, period: str, fetch) -> pd.DataFrame:
    """Return daily OHLCV for `symbol` over `period`, history pinned to the
    stored vintage. `fetch(symbol, period, interval, start, end)` is the
    live downloader (providers' fallback chain)."""
    path = _cache_path(symbol)
    cached = _load(path)
    bumped = False

    if cached is None or cached.empty:
        merged = _full_fetch(symbol, fetch)
        bumped = True
    else:
        fresh = fetch(symbol, TAIL_PERIOD, "1d", None, None)
        # La última barra guardada es provisional: pudo escribirse a media
        # sesión (el ciclo corre intradía y cripto/FX nunca "cierran"), así
        # que se excluye del chequeo de empalme y se reemplaza con la fresca.
        base = cached[cached.index < cached.index.max()]
        common = base.index.intersection(fresh.index)
        if len(common) == 0:
            # sin traslape utilizable (hueco largo): añada nueva deliberada
            merged = _full_fetch(symbol, fetch)
            bumped = True
        else:
            diff_pct = ((fresh.loc[common, "Close"] - base.loc[common, "Close"]).abs()
                        / base.loc[common, "Close"] * 100)
            if float(diff_pct.max()) > SEAM_TOL_PCT:
                print(
                    f"[vintage] {symbol}: revisión de datos detectada en el empalme "
                    f"(máx {float(diff_pct.max()):.2f}% > {SEAM_TOL_PCT}%) — añada nueva completa",
                    file=sys.stderr,
                )
                merged = _full_fetch(symbol, fetch)
                bumped = True
            else:
                new_rows = fresh[fresh.index > base.index.max()]
                merged = pd.concat([base, new_rows]) if len(new_rows) else cached

    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    _save(path, merged)
    cutoff = pd.Timestamp.today().normalize() - pd.DateOffset(days=_period_to_days(period))
    out = merged[merged.index >= cutoff].copy()
    out.attrs["vintage_bumped"] = bumped
    return out
