"""Day-by-day portfolio simulator.

Starting from a given date, walks forward one trading day at a time,
recomputing the ensemble recommendation for each symbol in the portfolio
using only data available up to and including that day (no lookahead — the
same information a live trader would have had), and converts each day's
BUY/SELL/HOLD call into that day's target position for that symbol. The
portfolio itself is auto-selected the same way, using only data available
*before* the start date: whichever symbols had the strongest BUY/SELL
conviction right before the simulation begins.

This directly answers "run a simulated portfolio day by day from date X and
tell me the profit/loss" — as opposed to `app.simulate` (one symbol, one
strategy) or `app.opportunities` (a single snapshot in time, not a period).
"""

from __future__ import annotations

import pandas as pd

from app.backtest.engine import extract_trades
from app.backtest.metrics import compute_metrics
from app.config import EXAMPLE_SYMBOLS, default_commission_bps
from app.data.providers import get_ohlcv
from app.data.synthetic import generate_ohlcv
from app.recommend.engine import recommend

MIN_WARMUP_BARS = 120

# A single default synthetic scenario for this feature: ~3 years of
# "historial previo" (so real dates like 2026-01-01 fall well after warmup),
# then a handful of distinct regimes for the simulated period itself so
# different symbols behave differently once the walk-forward starts.
_SYNTHETIC_START_DATE = "2023-01-01"
_WARMUP_DAYS = 1096  # 2023-01-01 + 1096 days lands right around 2026-01-01
DEFAULT_PORTFOLIO_PROFILES = [
    {
        "label": "Símbolo A (tendencia alcista)",
        "regimes": [
            {"name": "historial previo", "days": _WARMUP_DAYS, "drift": 0.0006, "volatility": 0.013},
            {"name": "alza 2026", "days": 90, "drift": 0.0018, "volatility": 0.013},
        ],
    },
    {
        "label": "Símbolo B (tendencia bajista)",
        "regimes": [
            {"name": "historial previo", "days": _WARMUP_DAYS, "drift": 0.0004, "volatility": 0.014},
            {"name": "baja 2026", "days": 90, "drift": -0.0018, "volatility": 0.015},
        ],
    },
    {
        "label": "Símbolo C (lateral)",
        "regimes": [
            {"name": "historial previo", "days": _WARMUP_DAYS, "drift": 0.0005, "volatility": 0.012},
            {"name": "lateral 2026", "days": 90, "drift": 0.0001, "volatility": 0.009},
        ],
    },
    {
        "label": "Símbolo D (volátil)",
        "regimes": [
            {"name": "historial previo", "days": _WARMUP_DAYS, "drift": 0.0005, "volatility": 0.013},
            {"name": "volátil 2026", "days": 90, "drift": 0.0004, "volatility": 0.028},
        ],
    },
    {
        "label": "Símbolo E (mixto)",
        "regimes": [
            {"name": "historial previo", "days": _WARMUP_DAYS, "drift": 0.0005, "volatility": 0.013},
            {"name": "corrección 2026", "days": 30, "drift": -0.003, "volatility": 0.02},
            {"name": "recuperación 2026", "days": 60, "drift": 0.0022, "volatility": 0.015},
        ],
    },
]

DISCLAIMER = (
    "Simulación histórica basada únicamente en indicadores técnicos; no es asesoría "
    "financiera y no garantiza resultados futuros. El desempeño pasado, incluso el de "
    "este mismo motor, no predice el desempeño futuro."
)


def _default_symbols() -> list[str]:
    return [entry["symbol"] for symbols in EXAMPLE_SYMBOLS.values() for entry in symbols]


def _find_start_index(df: pd.DataFrame, start_date: str) -> int:
    return int(df.index.searchsorted(pd.Timestamp(start_date)))


def _select_portfolio(
    dfs: dict[str, pd.DataFrame],
    start_idx_by_symbol: dict[str, int],
    portfolio_size: int,
    allow_short: bool,
    initial_capital: float,
    commission_bps: float | None,
    min_confidence_pct: float = 55.0,
) -> list[dict]:
    """Ranks symbols by ensemble confidence using only data strictly before
    the simulation's start index (no lookahead), and returns the top
    `portfolio_size` — BUY and SELL/short candidates when shorts are
    allowed, BUY-only otherwise (there's no point holding a bearish call you
    can't act on). Candidates below `min_confidence_pct` are excluded
    outright, same bar the daily walk-forward uses to decide whether to act
    on a signal — a portfolio built on a coin-flip call isn't a real
    portfolio, it's noise."""
    allowed_actions = {"BUY", "SELL"} if allow_short else {"BUY"}
    candidates = []
    for symbol, df in dfs.items():
        idx = start_idx_by_symbol[symbol]
        if idx < MIN_WARMUP_BARS:
            continue
        window = df.iloc[:idx]  # strictly before the first simulated day
        rec = recommend(
            window, symbol=symbol, initial_capital=initial_capital, commission_bps=commission_bps, allow_short=allow_short
        )
        if rec["overall_action"] in allowed_actions and rec["confidence_pct"] >= min_confidence_pct:
            candidates.append(
                {"symbol": symbol, "action_at_selection": rec["overall_action"], "confidence_pct_at_selection": rec["confidence_pct"]}
            )
    candidates.sort(key=lambda c: c["confidence_pct_at_selection"], reverse=True)
    return candidates[:portfolio_size]


def _walk_forward_result(
    df: pd.DataFrame,
    start_idx: int,
    symbol: str,
    allow_short: bool,
    capital: float,
    commission_bps: float | None,
    step: int,
    min_confidence_pct: float = 55.0,
) -> dict:
    """Recomputes the ensemble recommendation every `step` bars from
    `start_idx` onward (using only df.iloc[:t+1] each time — never later
    data), converts each decision into a target position, and evaluates the
    resulting equity curve with the same math as `app.backtest.engine`.

    A BUY/SELL call below `min_confidence_pct` is treated like a HOLD (keeps
    the current position instead of flipping) — a weak, near-coin-flip signal
    flipping the position anyway is exactly what turns a noisy/range-bound
    stretch into overtrading: extra commission drag plus a position that
    reverses right before the market does. This doesn't change what
    `recommend()` reports, only whether the simulator acts on it.

    `commission_bps=None` resolves once to a realistic default for `symbol`'s
    instrument type — resolved here (not left to `recommend()`/`run_backtest`
    to resolve internally) because this function also uses it directly for
    its own equity-curve math below."""
    if commission_bps is None:
        commission_bps = default_commission_bps(symbol)

    positions = [0] * len(df)
    current = 0
    for t in range(start_idx, len(df)):
        if (t - start_idx) % step == 0:
            window = df.iloc[: t + 1]
            rec = recommend(window, symbol=symbol, initial_capital=capital, commission_bps=commission_bps, allow_short=allow_short)
            action = rec["overall_action"]
            if rec["confidence_pct"] >= min_confidence_pct:
                if action == "BUY":
                    current = 1
                elif action == "SELL":
                    current = -1 if allow_short else 0
            # HOLD, or a BUY/SELL below the confidence threshold: keep `current` unchanged.
        positions[t] = current

    sim_df = df.iloc[start_idx:].copy()
    sim_df["position"] = pd.Series(positions, index=df.index).iloc[start_idx:]

    daily_returns = sim_df["Close"].pct_change().fillna(0)
    position_shifted = sim_df["position"].shift(1).fillna(0)
    trade_changes = sim_df["position"].diff().abs().fillna(0)
    commission_rate = commission_bps / 10000
    period_returns = position_shifted * daily_returns - trade_changes * commission_rate
    equity_curve = capital * (1 + period_returns).cumprod()

    trades = extract_trades(sim_df, commission_bps, equity_curve=equity_curve, initial_capital=capital)
    metrics = compute_metrics(equity_curve, trades, period_returns)

    for trade in trades:
        trade["symbol"] = symbol

    return {"symbol": symbol, "equity_curve": equity_curve, "trades": trades, "metrics": metrics}


def _combine_equity_curves(results: list[dict], capital_per_symbol: float) -> pd.Series:
    all_dates = sorted(set().union(*(r["equity_curve"].index for r in results)))
    combined = pd.Series(0.0, index=all_dates)
    for r in results:
        aligned = r["equity_curve"].reindex(all_dates)
        aligned = aligned.ffill().fillna(capital_per_symbol)
        combined = combined.add(aligned, fill_value=0.0)
    return combined


def _run_simulation(
    dfs: dict[str, pd.DataFrame],
    start_date: str,
    end_date: str | None,
    portfolio_size: int,
    initial_capital: float,
    commission_bps: float | None,
    allow_short: bool,
    step: int,
    errors: dict[str, str],
    min_confidence_pct: float = 55.0,
) -> dict:
    if step < 1:
        raise ValueError("step debe ser >= 1")

    if end_date:
        dfs = {symbol: df[df.index <= pd.Timestamp(end_date)] for symbol, df in dfs.items()}

    start_idx_by_symbol = {symbol: _find_start_index(df, start_date) for symbol, df in dfs.items()}
    usable = {
        symbol: df
        for symbol, df in dfs.items()
        if MIN_WARMUP_BARS <= start_idx_by_symbol[symbol] < len(df) - 1
    }
    for symbol in dfs:
        if symbol not in usable:
            errors.setdefault(
                symbol,
                "Historial insuficiente antes de la fecha de inicio, o no hay barras después de esa fecha.",
            )

    portfolio = _select_portfolio(
        usable, start_idx_by_symbol, portfolio_size, allow_short, initial_capital, commission_bps, min_confidence_pct
    )
    if not portfolio:
        raise ValueError(
            "No se encontraron símbolos con señal BUY"
            + (" o SELL" if allow_short else "")
            + f" con al menos {min_confidence_pct}% de confianza antes de la fecha de inicio. "
            "Prueba con otro universo, fecha, un umbral de confianza más bajo, o habilita posiciones cortas."
        )

    capital_per_symbol = round(initial_capital / len(portfolio), 2)
    per_symbol_results = [
        _walk_forward_result(
            usable[c["symbol"]],
            start_idx_by_symbol[c["symbol"]],
            c["symbol"],
            allow_short,
            capital_per_symbol,
            commission_bps,
            step,
            min_confidence_pct,
        )
        for c in portfolio
    ]

    portfolio_equity_curve = _combine_equity_curves(per_symbol_results, capital_per_symbol)
    final_equity = round(float(portfolio_equity_curve.iloc[-1]), 2)
    num_trading_days = max(len(r["equity_curve"]) for r in per_symbol_results)

    return {
        "start_date": start_date,
        "end_date": str(portfolio_equity_curve.index[-1].date()),
        "num_trading_days": num_trading_days,
        "initial_capital": initial_capital,
        "capital_per_symbol": capital_per_symbol,
        "portfolio": portfolio,
        "final_equity": final_equity,
        "total_pnl_amount": round(final_equity - initial_capital, 2),
        "total_return_pct": round((final_equity / initial_capital - 1) * 100, 2),
        "per_symbol": [
            {
                "symbol": r["symbol"],
                "final_equity": round(float(r["equity_curve"].iloc[-1]), 2),
                "pnl_amount": round(float(r["equity_curve"].iloc[-1]) - capital_per_symbol, 2),
                "metrics": r["metrics"],
                "trades": r["trades"],
            }
            for r in per_symbol_results
        ],
        "portfolio_equity_curve": [
            {"date": str(d.date()), "equity": round(float(v), 2)} for d, v in portfolio_equity_curve.items()
        ],
        "errors": errors,
        "disclaimer": DISCLAIMER,
    }


def simulate_portfolio_real(
    start_date: str,
    end_date: str | None = None,
    symbols: list[str] | None = None,
    portfolio_size: int = 5,
    period: str = "3y",
    interval: str = "1d",
    initial_capital: float = 10_000.0,
    commission_bps: float | None = None,
    allow_short: bool = True,
    step: int = 1,
    min_confidence_pct: float = 55.0,
) -> dict:
    """Auto-selects a portfolio (from real symbols, defaulting to the full
    example universe) using only data before `start_date`, then walks
    forward day by day executing the ensemble recommendation's calls,
    reporting the combined dollar P&L over the period. `min_confidence_pct`
    is the minimum ensemble confidence required to select a symbol or flip
    its position on a given day — below it, a BUY/SELL call is treated as a
    HOLD, to avoid overtrading on weak/noisy signals."""
    symbols = symbols or _default_symbols()

    dfs = {}
    errors = {}
    for symbol in symbols:
        try:
            dfs[symbol] = get_ohlcv(symbol, period=period, interval=interval)
        except Exception as exc:  # data provider/network failures are per-symbol, not fatal for the whole scan
            errors[symbol] = str(exc)

    return _run_simulation(
        dfs, start_date, end_date, portfolio_size, initial_capital, commission_bps, allow_short, step, errors, min_confidence_pct
    )


def simulate_portfolio_synthetic(
    start_date: str = "2026-01-01",
    end_date: str | None = None,
    profiles: list[dict] | None = None,
    portfolio_size: int = 5,
    seed: int = 42,
    initial_capital: float = 10_000.0,
    commission_bps: float | None = None,
    allow_short: bool = True,
    step: int = 1,
    min_confidence_pct: float = 55.0,
) -> dict:
    """Same simulation, but over synthetic profiles reaching into 2026 —
    usable with no network access. Real dates only line up exactly with
    `DEFAULT_PORTFOLIO_PROFILES` (~3 years of synthetic warmup ending right
    around 2026-01-01); custom `profiles` need their own `start_date` picked
    so the requested `start_date` actually falls inside the generated range."""
    profiles = profiles or DEFAULT_PORTFOLIO_PROFILES

    dfs = {
        profile["label"]: generate_ohlcv(regimes=profile["regimes"], start_date=_SYNTHETIC_START_DATE, seed=seed)
        for profile in profiles
    }
    return _run_simulation(
        dfs, start_date, end_date, portfolio_size, initial_capital, commission_bps, allow_short, step, {}, min_confidence_pct
    )
