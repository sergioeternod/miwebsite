"""Picks today's portfolio using the app's actual selection logic (risk-
adjusted confidence + asset-class diversification cap), not just raw
confidence ranking — the same mechanism app.portfolio._select_portfolio uses
inside portfolio-sim, run standalone here (selection only, no walk-forward)
for a quick "what would the model pick today" check."""

import json

import pandas as pd

from app.config import EXAMPLE_SYMBOLS
from app.data.providers import get_ohlcv
from app.portfolio import _find_start_index, _select_portfolio

SYMBOLS = [entry["symbol"] for syms in EXAMPLE_SYMBOLS.values() for entry in syms]
TODAY = pd.Timestamp.now().date().isoformat()
PORTFOLIO_SIZE = 5

dfs = {}
errors = {}
for symbol in SYMBOLS:
    try:
        dfs[symbol] = get_ohlcv(symbol, period="2y")
    except Exception as exc:
        errors[symbol] = str(exc)

start_idx_by_symbol = {s: _find_start_index(df, TODAY) for s, df in dfs.items()}
portfolio = _select_portfolio(dfs, start_idx_by_symbol, PORTFOLIO_SIZE, True, 10_000.0, None, 55.0)

print(json.dumps({"as_of": TODAY, "portfolio": portfolio, "errors": errors}, indent=2, ensure_ascii=False, default=str))
