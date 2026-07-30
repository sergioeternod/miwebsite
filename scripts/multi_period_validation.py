"""Out-of-sample robustness check: does the fully improved model (risk-
adjusted + diversification-capped selection, risk-parity position sizing,
per-position stop-loss) consistently beat the original naive baseline
(plain-confidence selection, equal-weight sizing, no stop-loss), or did the
first result tested just get lucky on one period?

Runs the same comparison across 5 non-overlapping-ish 3-year windows
spanning different market regimes (early crypto era, 2018 bear, covid boom,
2022 bear + 2023 recovery, and the most recent 3 years), all on real market
data. Each period fetches its own bounded window instead of pulling full
history for every symbol (see WARMUP_YEARS/SIMULATED_YEARS below).

Note: unlike the first version of this script, the old and new methods now
use different capital allocations (equal-weight vs. risk-parity) and
different exit rules (no stop-loss vs. a 15% stop-loss), so a shared
symbol's walk-forward result is no longer interchangeable between the two
— each is computed separately, in exchange for the earlier run's cache-reuse
speedup.
"""

import json
import time

import pandas as pd

from app.config import EXAMPLE_SYMBOLS
from app.data.providers import get_ohlcv
from app.portfolio import (
    MIN_WARMUP_BARS,
    _combine_equity_curves,
    _find_start_index,
    _risk_parity_weights,
    _select_portfolio,
    _walk_forward_result,
)
from app.recommend.engine import recommend

SYMBOLS = [entry["symbol"] for syms in EXAMPLE_SYMBOLS.values() for entry in syms]

PERIODS = [
    {"label": "2014-07-30 -> 2017-07-30 (era cripto temprana)", "start_date": "2014-07-30"},
    {"label": "2017-07-30 -> 2020-07-30 (bajista/mixto)", "start_date": "2017-07-30"},
    {"label": "2019-07-30 -> 2022-07-30 (covid + recuperación + inicio bajista 2022)", "start_date": "2019-07-30"},
    {"label": "2021-07-30 -> 2024-07-30 (bajista 2022 + recuperación 2023)", "start_date": "2021-07-30"},
    {"label": "2023-07-30 -> 2026-07-30 (ya corrida antes)", "start_date": "2023-07-30"},
]
WARMUP_YEARS = 2
SIMULATED_YEARS = 3
PORTFOLIO_SIZE = 5
INITIAL_CAPITAL = 10_000.0
STEP = 1


def select_old_style(dfs, start_idx_by_symbol, portfolio_size):
    """Replicates the original pre-improvement ranking: pure confidence, no
    risk adjustment, no diversification cap — for comparison only."""
    candidates = []
    for symbol, df in dfs.items():
        idx = start_idx_by_symbol[symbol]
        if idx < MIN_WARMUP_BARS:
            continue
        window = df.iloc[:idx]
        rec = recommend(window, symbol=symbol, initial_capital=INITIAL_CAPITAL, commission_bps=None, allow_short=True)
        if rec["overall_action"] in {"BUY", "SELL"} and rec["confidence_pct"] >= 55.0:
            candidates.append(
                {"symbol": symbol, "action_at_selection": rec["overall_action"], "confidence_pct_at_selection": rec["confidence_pct"]}
            )
    candidates.sort(key=lambda c: c["confidence_pct_at_selection"], reverse=True)
    return candidates[:portfolio_size]


def run_portfolio_old(dfs, start_idx_by_symbol, portfolio):
    """Original baseline: equal-weight capital, no stop-loss."""
    capital_per_symbol = round(INITIAL_CAPITAL / len(portfolio), 2)
    capital_by_symbol = {c["symbol"]: capital_per_symbol for c in portfolio}
    results = [
        _walk_forward_result(
            dfs[c["symbol"]], start_idx_by_symbol[c["symbol"]], c["symbol"], True,
            capital_by_symbol[c["symbol"]], None, STEP, stop_loss_pct=None,
        )
        for c in portfolio
    ]
    equity_curve = _combine_equity_curves(results, capital_by_symbol)
    final_equity = round(float(equity_curve.iloc[-1]), 2)
    return {
        "final_equity": final_equity,
        "total_pnl_amount": round(final_equity - INITIAL_CAPITAL, 2),
        "total_return_pct": round((final_equity / INITIAL_CAPITAL - 1) * 100, 2),
    }


def run_portfolio_new(dfs, start_idx_by_symbol, portfolio):
    """Fully improved model: risk-adjusted + diversification-capped
    selection (already applied by the time `portfolio` is built), risk-parity
    sizing, and the default per-position stop-loss."""
    weights = _risk_parity_weights(portfolio)
    capital_by_symbol = {symbol: round(INITIAL_CAPITAL * w, 2) for symbol, w in weights.items()}
    results = [
        _walk_forward_result(
            dfs[c["symbol"]], start_idx_by_symbol[c["symbol"]], c["symbol"], True,
            capital_by_symbol[c["symbol"]], None, STEP,
        )
        for c in portfolio
    ]
    equity_curve = _combine_equity_curves(results, capital_by_symbol)
    final_equity = round(float(equity_curve.iloc[-1]), 2)
    return {
        "final_equity": final_equity,
        "total_pnl_amount": round(final_equity - INITIAL_CAPITAL, 2),
        "total_return_pct": round((final_equity / INITIAL_CAPITAL - 1) * 100, 2),
    }


if __name__ == "__main__":
    t0 = time.time()

    all_results = []
    all_errors = {}
    for period in PERIODS:
        print(f"\n=== Periodo: {period['label']} ===")
        start_ts = pd.Timestamp(period["start_date"])
        fetch_start = (start_ts - pd.DateOffset(years=WARMUP_YEARS)).date().isoformat()
        fetch_end = (start_ts + pd.DateOffset(years=SIMULATED_YEARS)).date().isoformat()

        print(f"  Fetching {fetch_start} -> {fetch_end} for {len(SYMBOLS)} symbols...")
        dfs = {}
        errors = {}
        for symbol in SYMBOLS:
            try:
                dfs[symbol] = get_ohlcv(symbol, start=fetch_start, end=fetch_end)
            except Exception as exc:
                errors[symbol] = str(exc)
        all_errors[period["start_date"]] = errors
        print(f"  Fetched {len(dfs)}/{len(SYMBOLS)} symbols, {len(errors)} errors.")

        start_idx_by_symbol = {s: _find_start_index(df, period["start_date"]) for s, df in dfs.items()}
        usable = {s: df for s, df in dfs.items() if MIN_WARMUP_BARS <= start_idx_by_symbol[s] < len(df) - 1}

        old_portfolio = select_old_style(usable, start_idx_by_symbol, PORTFOLIO_SIZE)
        new_portfolio = _select_portfolio(
            usable, start_idx_by_symbol, PORTFOLIO_SIZE, True, INITIAL_CAPITAL, None, 55.0
        )

        if not old_portfolio or not new_portfolio:
            print("  Sin candidatos suficientes en este periodo, se omite.")
            continue

        old_result = run_portfolio_old(usable, start_idx_by_symbol, old_portfolio)
        new_result = run_portfolio_new(usable, start_idx_by_symbol, new_portfolio)

        entry = {
            "period": period["label"],
            "start_date": period["start_date"],
            "old_portfolio": [c["symbol"] for c in old_portfolio],
            "old_result": old_result,
            "new_portfolio": [c["symbol"] for c in new_portfolio],
            "new_result": new_result,
            "improved": new_result["total_return_pct"] > old_result["total_return_pct"],
        }
        all_results.append(entry)
        print(f"  OLD {entry['old_portfolio']}: {old_result['total_pnl_amount']} ({old_result['total_return_pct']}%)")
        print(f"  NEW {entry['new_portfolio']}: {new_result['total_pnl_amount']} ({new_result['total_return_pct']}%)")
        print(f"  {'MEJORÓ' if entry['improved'] else 'NO MEJORÓ'}")

    elapsed = time.time() - t0
    num_improved = sum(1 for r in all_results if r["improved"])
    returns_delta = [r["new_result"]["total_return_pct"] - r["old_result"]["total_return_pct"] for r in all_results]
    avg_delta = round(sum(returns_delta) / len(returns_delta), 2) if returns_delta else None
    summary = {
        "elapsed_seconds": round(elapsed, 1),
        "num_periods_tested": len(all_results),
        "num_periods_improved": num_improved,
        "avg_return_pct_delta": avg_delta,
        "results": all_results,
        "fetch_errors": all_errors,
    }
    with open("scripts/multi_period_validation_result.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, default=str)

    print(f"\n\n=== RESUMEN: {num_improved}/{len(all_results)} periodos mejoraron. Delta promedio de retorno: {avg_delta} pp ===")
    print(f"elapsed_seconds={elapsed:.1f}")
