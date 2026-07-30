"""Honest before/after: for the exact same universe and start date as the
earlier real 3-year run (which lost -29.06%, all short crypto/commodities/
index calls), does risk-adjusted selection (Sharpe/drawdown-aware) pick a
different portfolio than plain confidence ranking would have?"""

import json

from app.config import EXAMPLE_SYMBOLS
from app.data.providers import get_ohlcv
from app.portfolio import MIN_WARMUP_BARS, _find_start_index, _risk_multiplier
from app.recommend.engine import recommend

START_DATE = "2023-07-30"
PERIOD = "5y"
PORTFOLIO_SIZE = 5

symbols = [entry["symbol"] for syms in EXAMPLE_SYMBOLS.values() for entry in syms]

by_confidence = []
by_risk_adjusted = []
errors = {}

for symbol in symbols:
    try:
        df = get_ohlcv(symbol, period=PERIOD)
    except Exception as exc:
        errors[symbol] = str(exc)
        continue

    idx = _find_start_index(df, START_DATE)
    if idx < MIN_WARMUP_BARS:
        continue
    window = df.iloc[:idx]
    rec = recommend(window, symbol=symbol, initial_capital=10_000.0, commission_bps=None, allow_short=True)
    if rec["overall_action"] not in {"BUY", "SELL"} or rec["confidence_pct"] < 55.0:
        continue

    best = rec["best_historical_strategy"]
    risk_mult = _risk_multiplier(best.get("sharpe_ratio"), best.get("max_drawdown_pct"))
    entry = {
        "symbol": symbol,
        "action": rec["overall_action"],
        "confidence_pct": rec["confidence_pct"],
        "sharpe_ratio": best.get("sharpe_ratio"),
        "max_drawdown_pct": best.get("max_drawdown_pct"),
        "risk_adjusted_score": round(rec["confidence_pct"] * risk_mult, 2),
    }
    by_confidence.append(entry)
    by_risk_adjusted.append(entry)

by_confidence.sort(key=lambda c: c["confidence_pct"], reverse=True)
by_risk_adjusted.sort(key=lambda c: c["risk_adjusted_score"], reverse=True)

result = {
    "start_date": START_DATE,
    "old_portfolio_by_confidence": by_confidence[:PORTFOLIO_SIZE],
    "new_portfolio_by_risk_adjusted": by_risk_adjusted[:PORTFOLIO_SIZE],
    "errors": errors,
}

with open("scripts/compare_selection_result.json", "w", encoding="utf-8") as f:
    json.dump(result, f, indent=2, ensure_ascii=False, default=str)

print("OLD (by raw confidence):")
for c in by_confidence[:PORTFOLIO_SIZE]:
    print(f"  {c['symbol']}: {c['action']} conf={c['confidence_pct']} sharpe={c['sharpe_ratio']} dd={c['max_drawdown_pct']}")

print("\nNEW (by risk-adjusted score):")
for c in by_risk_adjusted[:PORTFOLIO_SIZE]:
    print(f"  {c['symbol']}: {c['action']} conf={c['confidence_pct']} sharpe={c['sharpe_ratio']} dd={c['max_drawdown_pct']} score={c['risk_adjusted_score']}")

if errors:
    print("\nerrors:", errors)
