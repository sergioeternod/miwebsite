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

Portfolio *selection* (`_select_portfolio`) can optionally factor in the
earnings-surprise and news-sentiment overlays (`app.fundamentals.earnings`,
`app.fundamentals.news_sentiment` — the same ones `app.opportunities` uses)
and each candidate's own historical risk stats (Sharpe ratio, max drawdown).
The day-by-day walk-forward (`_walk_forward_result`) deliberately does
*not* apply the earnings/news overlays, for two concrete reasons: (1)
Finnhub's and Alpha Vantage's free endpoints return data relative to *now*
(the real clock), with no "as of this past date" parameter — pulling them
into a re-evaluation of, say, 2023-08-15 during a backtest would silently
leak today's news/earnings into a decision timestamped years ago, a real
lookahead bug, not a stylistic choice; and (2) even ignoring correctness,
a multi-year daily walk-forward makes thousands of calls per symbol, which
blows through both providers' free-tier rate limits almost immediately.
Both overlays remain exactly what they always were: a live, current-moment
nudge — sound for *choosing today's portfolio*, not for re-litigating every
past day of it.
"""

from __future__ import annotations

import pandas as pd

from app.backtest.engine import extract_trades
from app.backtest.metrics import compute_metrics
from app.config import EXAMPLE_SYMBOLS, AssetClass, default_commission_bps, infer_asset_class
from app.data.providers import get_ohlcv
from app.data.synthetic import generate_ohlcv
from app.fundamentals.earnings import apply_earnings_overlay
from app.fundamentals.news_sentiment import apply_news_overlay
from app.recommend.engine import recommend
from app.validation.trade_accuracy import annotate_trade_hindsight, hindsight_summary

MIN_WARMUP_BARS = 120

# Risk-adjusted portfolio selection: a candidate's raw ensemble confidence is
# scaled by how well its own winning strategy has historically performed on
# a *risk-adjusted* basis (Sharpe ratio) and how deep its worst historical
# drawdown was — so a symbol with a loud, high-confidence call but a rough,
# high-drawdown/low-Sharpe track record doesn't automatically outrank a
# calmer, more consistent one. This is a multiplier on confidence, not a
# replacement for it: a technically weak call still can't win on stats alone.
SHARPE_MULTIPLIER_FLOOR = 0.6
SHARPE_MULTIPLIER_CEILING = 1.4
SHARPE_NORMALIZATION_RANGE = 3.0  # Sharpe ratios below -1 or above +2 saturate the multiplier
DRAWDOWN_PENALTY_SATURATION_PCT = 50.0  # a -50% (or deeper) historical drawdown maxes out the penalty
DRAWDOWN_MULTIPLIER_FLOOR = 0.5


def _risk_multiplier(sharpe_ratio: float | None, max_drawdown_pct: float | None) -> float:
    """Turns a candidate's own historical Sharpe ratio and max drawdown into
    a multiplier on its ensemble confidence: `SHARPE_MULTIPLIER_FLOOR` (a bad
    Sharpe) to `SHARPE_MULTIPLIER_CEILING` (a strong one), further scaled
    down by `DRAWDOWN_MULTIPLIER_FLOOR` at the deepest historical drawdowns.
    Missing stats (e.g. a strategy with too few historical trades to compute
    a Sharpe ratio) are treated as neutral (1.0), not penalized — there's no
    evidence either way, so it shouldn't count against the candidate."""
    if sharpe_ratio is None or pd.isna(sharpe_ratio):
        sharpe_multiplier = 1.0
    else:
        sharpe_component = min(max((sharpe_ratio + 1.0) / SHARPE_NORMALIZATION_RANGE, 0.0), 1.0)
        sharpe_multiplier = SHARPE_MULTIPLIER_FLOOR + (SHARPE_MULTIPLIER_CEILING - SHARPE_MULTIPLIER_FLOOR) * sharpe_component

    if max_drawdown_pct is None or pd.isna(max_drawdown_pct):
        drawdown_multiplier = 1.0
    else:
        drawdown_component = min(abs(max_drawdown_pct) / DRAWDOWN_PENALTY_SATURATION_PCT, 1.0)
        drawdown_multiplier = 1.0 - (1.0 - DRAWDOWN_MULTIPLIER_FLOOR) * drawdown_component

    return sharpe_multiplier * drawdown_multiplier


# Diversification cap: without this, nothing stops the top N candidates by
# score from being 2-3 flavors of the same bet (e.g. BTC-USD *and* ETH-USD
# both short at once) — same trade, twice the exposure, not real
# diversification. Capping how many picks can come from one asset class
# forces the rest of the portfolio slots to come from elsewhere.
DEFAULT_MAX_PER_ASSET_CLASS = 2

# Risk-parity position sizing: instead of splitting capital equally across
# selected symbols, size each position inversely to its own historical daily
# volatility, so a calm instrument (e.g. a major forex pair) gets more
# capital than a wild one (e.g. crypto) for the same portfolio slot — this
# captures *some* upside from a volatile pick without giving it the same
# dollar exposure as a stable one, instead of the earlier all-or-nothing
# choice between including it at full size or excluding it outright.
MIN_VOLATILITY_PCT = 0.1  # floor so a near-flat instrument doesn't dominate the weights


def _risk_parity_weights(portfolio: list[dict]) -> dict[str, float]:
    """Inverse-volatility weights for the selected `portfolio`, normalized to
    sum to 1.0. A missing/zero volatility reading is floored to
    `MIN_VOLATILITY_PCT` rather than treated as "infinitely safe" — otherwise
    a single degenerate reading could claim almost all the capital."""
    inv_vols = {
        c["symbol"]: 1.0 / max(c.get("volatility_pct") or MIN_VOLATILITY_PCT, MIN_VOLATILITY_PCT)
        for c in portfolio
    }
    total = sum(inv_vols.values())
    return {symbol: inv_vol / total for symbol, inv_vol in inv_vols.items()}


# "Learning from old positions": every `step` bars, before deciding the next
# position, the simulator looks back — causally, only at trades that already
# closed — and checks whether those positions were the best of long/short/
# flat in hindsight (app.validation.trade_accuracy.annotate_trade_hindsight).
# A run of bad-in-hindsight calls temporarily raises the confidence bar
# required to act, up to ADAPTIVE_REGRET_MAX_BOOST points, so the simulator
# gets pickier after a losing streak instead of repeating it at the same
# threshold. This adapts caution, not the underlying prediction — it cannot
# turn a wrong call right, only make the next one need more conviction.
ADAPTIVE_REGRET_LOOKBACK = 3
ADAPTIVE_REGRET_MAX_BOOST = 20.0

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


def _buy_hold_benchmark(
    usable: dict[str, pd.DataFrame],
    start_idx_by_symbol: dict[str, int],
    capital_by_symbol: dict[str, float],
    commission_bps: float | None,
) -> dict:
    """The honesty yardstick: same symbols, same capital split, bought at the
    first simulated bar's close and never touched again (one entry commission,
    long-only regardless of what the model's call was). Every simulation
    report carries this so an "up 20%" run can't quietly hide that doing
    nothing would have made more — the gap to this number, not the raw
    return, is what the daily recalculation actually earned."""
    per_symbol = {}
    for symbol, capital in capital_by_symbol.items():
        df = usable[symbol]
        window = df.iloc[start_idx_by_symbol[symbol]:]
        bps = commission_bps if commission_bps is not None else default_commission_bps(symbol)
        gross = float(window["Close"].iloc[-1]) / float(window["Close"].iloc[0])
        per_symbol[symbol] = round(capital * gross * (1 - bps / 10000), 2)

    final_equity = round(sum(per_symbol.values()), 2)
    initial_capital = round(sum(capital_by_symbol.values()), 2)
    return {
        "description": (
            "Mismos símbolos y mismo reparto de capital, comprados (long) al cierre del primer "
            "día simulado y mantenidos sin operar hasta el final — el punto de comparación pasivo."
        ),
        "final_equity": final_equity,
        "total_pnl_amount": round(final_equity - initial_capital, 2),
        "total_return_pct": round((final_equity / initial_capital - 1) * 100, 2),
        "per_symbol": per_symbol,
    }


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
    include_earnings: bool = False,
    include_news: bool = False,
    max_per_asset_class: int | None = DEFAULT_MAX_PER_ASSET_CLASS,
    short_confidence_premium: float = 0.0,
) -> list[dict]:
    """Ranks symbols using only data strictly before the simulation's start
    index (no lookahead), and returns the top `portfolio_size` — BUY and
    SELL/short candidates when shorts are allowed, BUY-only otherwise
    (there's no point holding a bearish call you can't act on).

    Ranking isn't raw ensemble confidence anymore: each candidate's
    confidence is first optionally nudged by the earnings/news overlays
    (`include_earnings`/`include_news` — real-ticker stocks only; see module
    docstring for why these apply *here* and not inside the day-by-day
    walk-forward), then scaled by `_risk_multiplier` using that candidate's
    own historical Sharpe ratio and max drawdown — so a loud, high-confidence
    call with a rough risk history doesn't automatically outrank a calmer,
    more consistent one. Candidates below `min_confidence_pct` (checked
    *after* any overlay nudge) are excluded outright, same bar the daily
    walk-forward uses to decide whether to act on a signal — a portfolio
    built on a coin-flip call isn't a real portfolio, it's noise.

    `max_per_asset_class` (default `DEFAULT_MAX_PER_ASSET_CLASS`, `None` to
    disable) caps how many picks can come from the same asset class —
    otherwise the top-N by score can end up as two or three flavors of the
    same bet (e.g. BTC-USD *and* ETH-USD both short at once), which is
    concentrated exposure, not diversification. A candidate that would
    exceed its class's cap is skipped in favor of the next-best one from a
    class with room left, rather than shrinking the portfolio."""
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
        if include_earnings:
            rec = apply_earnings_overlay(rec, symbol)
        if include_news:
            rec = apply_news_overlay(rec, symbol)

        required_confidence = min_confidence_pct
        if rec["overall_action"] == "SELL":
            # Same asymmetry gate the walk-forward applies (see
            # _walk_forward_result on short_confidence_premium): a short
            # candidate must clear a higher conviction bar than a long one.
            required_confidence += short_confidence_premium
        if rec["overall_action"] not in allowed_actions or rec["confidence_pct"] < required_confidence:
            continue

        best_strategy = rec.get("best_historical_strategy", {})
        risk_multiplier = _risk_multiplier(best_strategy.get("sharpe_ratio"), best_strategy.get("max_drawdown_pct"))
        volatility_pct = float(window["Close"].pct_change().std() * 100) if len(window) > 1 else None
        candidate = {
            "symbol": symbol,
            "action_at_selection": rec["overall_action"],
            "confidence_pct_at_selection": rec["confidence_pct"],
            "sharpe_ratio": best_strategy.get("sharpe_ratio"),
            "max_drawdown_pct": best_strategy.get("max_drawdown_pct"),
            "volatility_pct": round(volatility_pct, 3) if volatility_pct is not None and not pd.isna(volatility_pct) else None,
            "risk_adjusted_score": round(rec["confidence_pct"] * risk_multiplier, 2),
        }
        if include_earnings:
            candidate["earnings"] = rec.get("earnings")
        if include_news:
            candidate["news"] = rec.get("news")
        candidates.append(candidate)

    candidates.sort(key=lambda c: c["risk_adjusted_score"], reverse=True)

    if max_per_asset_class is None:
        return candidates[:portfolio_size]

    selected = []
    picks_per_class = {}
    for candidate in candidates:
        if len(selected) >= portfolio_size:
            break
        asset_class = infer_asset_class(candidate["symbol"])
        if picks_per_class.get(asset_class, 0) >= max_per_asset_class:
            continue
        selected.append(candidate)
        picks_per_class[asset_class] = picks_per_class.get(asset_class, 0) + 1
    return selected


def _closed_trades_so_far(
    df: pd.DataFrame,
    positions: list[int],
    start_idx: int,
    t: int,
    commission_bps: float,
    capital: float,
) -> list[dict]:
    """Trades implied by the positions already decided for bars
    `[start_idx, t)` — never `t` itself, which is still being decided.
    Used only to look back at the simulator's own recent track record; the
    resulting trades' `equity_at_entry` falls back to `capital` (no
    `equity_curve` is passed) since this is a same-symbol sub-slice, not the
    period's own accounting."""
    if t <= start_idx:
        return []
    sub_df = df.iloc[start_idx:t].copy()
    sub_df["position"] = pd.Series(positions[start_idx:t], index=sub_df.index)
    return extract_trades(sub_df, commission_bps, equity_curve=None, initial_capital=capital)


def _recent_regret_boost(closed_trades: list[dict], commission_bps: float) -> float:
    """How much extra confidence to demand right now, based on how badly the
    last few *closed* trades did in hindsight (see
    `app.validation.trade_accuracy.annotate_trade_hindsight`). A streak of
    trades that, in hindsight, should have gone the other way (or stayed
    flat) raises the bar for the next call — capped at
    `ADAPTIVE_REGRET_MAX_BOOST` so it can dampen but never fully silence the
    simulator."""
    annotated = annotate_trade_hindsight(closed_trades, commission_bps=commission_bps)
    closed = [t for t in annotated if t.get("hindsight") is not None]
    if not closed:
        return 0.0
    recent = closed[-ADAPTIVE_REGRET_LOOKBACK:]
    avg_regret_pct = sum(t["hindsight"]["regret_pct"] for t in recent) / len(recent)
    return min(avg_regret_pct, ADAPTIVE_REGRET_MAX_BOOST)


DEFAULT_STOP_LOSS_PCT = 15.0


# Equity-regime tilt: the model's cross-asset diversification (forex, gold,
# commodities) is what protects it in bad markets — and what anchors it in
# strong equity years, where those assets barely move while stocks rally
# (measured: Aug-2025→Aug-2026 the model made +7.6% vs +22-26% for the pure
# indexes, with the drag coming from forex/gold picks). The tilt is a
# classic, causal trend filter: at a (re)selection boundary, if the broad
# equity market trades above its long moving average — knowable that day,
# no lookahead — the candidate universe narrows to stocks and indexes (and
# the per-class cap lifts, since diversification then comes from multiple
# equity names); below it, the full defensive universe returns.
EQUITY_TILT_REGIME_SYMBOL = "^GSPC"
EQUITY_TILT_SMA_WINDOW = 200
_EQUITY_CLASSES = {AssetClass.STOCK, AssetClass.INDEX}


def _equity_risk_on(
    dfs: dict[str, pd.DataFrame],
    start_idx_by_symbol: dict[str, int],
    regime_symbol: str = EQUITY_TILT_REGIME_SYMBOL,
    sma_window: int = EQUITY_TILT_SMA_WINDOW,
) -> bool | None:
    """True when the regime symbol's last close strictly before the boundary
    sits above its `sma_window`-bar moving average — the standard "market in
    an uptrend" reading, computed only from data a trader would have had at
    that boundary. Returns None (tilt not applicable, caller changes
    nothing) when the regime symbol is missing or has less history than the
    moving average needs."""
    df = dfs.get(regime_symbol)
    if df is None:
        return None
    idx = start_idx_by_symbol.get(regime_symbol, 0)
    if idx < sma_window:
        return None
    closes = df["Close"].iloc[:idx]
    return bool(float(closes.iloc[-1]) > float(closes.tail(sma_window).mean()))


def _apply_equity_tilt(
    usable: dict[str, pd.DataFrame],
    risk_on: bool | None,
    max_per_asset_class: int | None,
) -> tuple[dict[str, pd.DataFrame], int | None]:
    """Returns the (universe, per-class cap) the selection should actually
    use: narrowed to equity classes with the cap lifted when risk-on, and
    untouched otherwise — including when the narrowed universe would be
    empty (an equity tilt with no equities to pick is a no-op, not a
    lockout)."""
    if not risk_on:
        return usable, max_per_asset_class
    equities = {s: df for s, df in usable.items() if infer_asset_class(s) in _EQUITY_CLASSES}
    if not equities:
        return usable, max_per_asset_class
    return equities, None


def _stop_loss_triggered(price_today: float, entry_price: float, direction: int, stop_loss_pct: float) -> bool:
    """`direction` is the position's sign (+1 long, -1 short). Multiplying
    the raw price-ratio move by `direction` turns "which way did price move"
    into "did this specific position gain or lose" — a short gains when
    price falls, so the same falling price that would trip a long's stop
    is exactly what a short wants."""
    move_in_position_direction_pct = (price_today / entry_price - 1) * 100 * direction
    return move_in_position_direction_pct <= -stop_loss_pct


# Risk-regime position scaling: crashes weren't predictable in this engine's
# own record (verified empirically — the eve of the Aug-2024 drop read HOLD
# with RSI already reacting, and the Jan-2026 peak read HOLD 80.6% with zero
# warning), but *rising realized volatility* is measurable the moment it
# appears. This indicator doesn't try to call the top; it shrinks how much a
# hit hurts: when recent (short-window) volatility runs above the longer-term
# baseline, position exposure is scaled down proportionally, recovering to
# full size when volatility normalizes.
VOL_REGIME_SHORT_WINDOW = 20  # ~1 trading month of daily bars
VOL_REGIME_LONG_WINDOW = 100  # ~5 trading months: the "normal" baseline
VOL_REGIME_MIN_EXPOSURE = 0.25  # never fully exits — this dampens, the signal/stop-loss decide exits


def _vol_regime_exposure(close: pd.Series) -> pd.Series:
    """Per-bar exposure fraction in [`VOL_REGIME_MIN_EXPOSURE`, 1.0]:
    `long_window_vol / short_window_vol`, capped at 1.0 — so calm or
    calming markets trade at full size and a volatility spike cuts size
    roughly in proportion to how far current vol exceeds its baseline.

    Causal by construction: each bar's value comes from `rolling()` windows
    ending at that bar, so bar t's exposure uses only closes up to t — the
    same no-lookahead guarantee as the rest of the walk-forward. Bars
    without enough history (and degenerate zero-vol stretches) default to
    full exposure (1.0): no evidence of elevated risk isn't evidence of
    risk."""
    returns = close.pct_change()
    # ddof=0 (population std) so windows of different lengths measuring the
    # *same* underlying volatility produce the same number — with the default
    # ddof=1, the shorter window reads systematically higher and a perfectly
    # steady market would get (slightly) penalized for nothing.
    short_vol = returns.rolling(VOL_REGIME_SHORT_WINDOW).std(ddof=0)
    long_vol = returns.rolling(VOL_REGIME_LONG_WINDOW).std(ddof=0)
    ratio = (long_vol / short_vol).replace([float("inf"), float("-inf")], 1.0)
    return ratio.clip(lower=VOL_REGIME_MIN_EXPOSURE, upper=1.0).fillna(1.0)


def _walk_forward_result(
    df: pd.DataFrame,
    start_idx: int,
    symbol: str,
    allow_short: bool,
    capital: float,
    commission_bps: float | None,
    step: int,
    min_confidence_pct: float = 55.0,
    adaptive_learning: bool = True,
    stop_loss_pct: float | None = DEFAULT_STOP_LOSS_PCT,
    short_confidence_premium: float = 0.0,
    risk_regime_sizing: bool = False,
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

    When `adaptive_learning` is on, that confidence bar isn't fixed: at each
    decision point the simulator looks back — causally, only at trades that
    already closed strictly before this point — and raises the bar further
    after a streak of calls that, in hindsight, should have gone the other
    way (see `_recent_regret_boost`). This adapts caution based on the
    simulator's own recent track record; it cannot see the future and cannot
    turn a wrong call into a right one, only make the next one need more
    conviction.

    `stop_loss_pct` (default `DEFAULT_STOP_LOSS_PCT`, `None` to disable) is a
    hard exit the ensemble's own signal can't override: checked every bar
    (not just every `step` bars — a risk control that only fires on the
    scheduled recalculation day isn't a real safety net), if a position has
    lost more than `stop_loss_pct` since it was opened, it's flattened
    regardless of what the technical signal currently says. This is the one
    exit rule in this simulator that doesn't wait for `recommend()` to
    change its mind.

    `short_confidence_premium` (default 0, i.e. off) demands that many extra
    confidence points before acting on a SELL when shorts are enabled —
    grounded in the measured asymmetry that this engine's shorts lost money
    in every saved multi-year run while its longs made money in all of them
    (markets drift upward over long horizons, so a short is a bet against
    the baseline, not just against the symbol). It only gates *opening or
    holding into* a short; a SELL under `allow_short=False` (which merely
    flattens a long, a defensive move) is never premium-gated.

    `risk_regime_sizing` (default off, pending validation) applies
    `_vol_regime_exposure` to the position: same entries and exits, but the
    dollar exposure of whatever position is held shrinks while short-term
    realized volatility runs above its longer-term baseline. Commissions
    are charged on changes in *effective* exposure (position × scale), so
    the gradual re-scaling itself pays trading costs rather than being
    modeled as free.

    `commission_bps=None` resolves once to a realistic default for `symbol`'s
    instrument type — resolved here (not left to `recommend()`/`run_backtest`
    to resolve internally) because this function also uses it directly for
    its own equity-curve math below."""
    if commission_bps is None:
        commission_bps = default_commission_bps(symbol)

    positions = [0] * len(df)
    current = 0
    entry_price = None
    for t in range(start_idx, len(df)):
        price_today = float(df["Close"].iloc[t])

        if stop_loss_pct is not None and current != 0 and entry_price is not None:
            if _stop_loss_triggered(price_today, entry_price, current, stop_loss_pct):
                current = 0
                entry_price = None

        if (t - start_idx) % step == 0:
            window = df.iloc[: t + 1]
            rec = recommend(window, symbol=symbol, initial_capital=capital, commission_bps=commission_bps, allow_short=allow_short)
            action = rec["overall_action"]
            effective_min_confidence = min_confidence_pct
            if adaptive_learning:
                closed_so_far = _closed_trades_so_far(df, positions, start_idx, t, commission_bps, capital)
                effective_min_confidence += _recent_regret_boost(closed_so_far, commission_bps)
            required_confidence = effective_min_confidence
            if action == "SELL" and allow_short:
                required_confidence += short_confidence_premium
            new_current = current
            if rec["confidence_pct"] >= required_confidence:
                if action == "BUY":
                    new_current = 1
                elif action == "SELL":
                    new_current = -1 if allow_short else 0
                # HOLD, or a BUY/SELL below the confidence threshold: keep `current` unchanged.
            if new_current != current:
                entry_price = price_today if new_current != 0 else None
            current = new_current
        positions[t] = current

    sim_df = df.iloc[start_idx:].copy()
    sim_df["position"] = pd.Series(positions, index=df.index).iloc[start_idx:]

    daily_returns = sim_df["Close"].pct_change().fillna(0)
    if risk_regime_sizing:
        # `_vol_regime_exposure` is causal (rolling windows ending at each
        # bar), so computing it over the full df and slicing is identical to
        # recomputing it inside the day loop — just far cheaper.
        exposure = _vol_regime_exposure(df["Close"]).iloc[start_idx:]
        effective_position = sim_df["position"] * exposure
    else:
        effective_position = sim_df["position"].astype(float)
    position_shifted = effective_position.shift(1).fillna(0)
    trade_changes = effective_position.diff().abs().fillna(0)
    commission_rate = commission_bps / 10000
    period_returns = position_shifted * daily_returns - trade_changes * commission_rate
    equity_curve = capital * (1 + period_returns).cumprod()

    trades = extract_trades(sim_df, commission_bps, equity_curve=equity_curve, initial_capital=capital)
    metrics = compute_metrics(equity_curve, trades, period_returns)

    trades = annotate_trade_hindsight(trades, commission_bps=commission_bps)
    for trade in trades:
        trade["symbol"] = symbol

    holding_bars = sim_df["position"] != 0
    if risk_regime_sizing and bool(holding_bars.any()):
        avg_exposure_pct = round(float(exposure[holding_bars].mean()) * 100, 1)
    else:
        avg_exposure_pct = 100.0

    return {
        "symbol": symbol,
        "equity_curve": equity_curve,
        "trades": trades,
        "metrics": metrics,
        "hindsight_summary": hindsight_summary(trades),
        "risk_regime_avg_exposure_pct": avg_exposure_pct,
    }


def _combine_equity_curves(results: list[dict], capital_by_symbol: dict[str, float]) -> pd.Series:
    """`capital_by_symbol` gives each result's own starting capital (not
    necessarily equal across symbols — see `_risk_parity_weights`), used to
    fill in a symbol's pre-entry days on the combined date axis."""
    all_dates = sorted(set().union(*(r["equity_curve"].index for r in results)))
    combined = pd.Series(0.0, index=all_dates)
    for r in results:
        aligned = r["equity_curve"].reindex(all_dates)
        aligned = aligned.ffill().fillna(capital_by_symbol[r["symbol"]])
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
    adaptive_learning: bool = True,
    include_earnings: bool = False,
    include_news: bool = False,
    max_per_asset_class: int | None = DEFAULT_MAX_PER_ASSET_CLASS,
    risk_parity_sizing: bool = True,
    stop_loss_pct: float | None = DEFAULT_STOP_LOSS_PCT,
    short_confidence_premium: float = 0.0,
    risk_regime_sizing: bool = False,
    rebalance_months: int | None = None,
    equity_regime_tilt: bool = False,
) -> dict:
    if step < 1:
        raise ValueError("step debe ser >= 1")
    if rebalance_months is not None:
        if rebalance_months < 1:
            raise ValueError("rebalance_months debe ser >= 1")
        return _run_rebalanced_simulation(
            dfs, start_date, end_date, portfolio_size, initial_capital, commission_bps,
            allow_short, step, errors, min_confidence_pct, adaptive_learning,
            include_earnings, include_news, max_per_asset_class, risk_parity_sizing,
            stop_loss_pct, short_confidence_premium, risk_regime_sizing, rebalance_months,
            equity_regime_tilt,
        )

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

    tilt_risk_on = _equity_risk_on(usable, start_idx_by_symbol) if equity_regime_tilt else None
    selection_universe, selection_cap = _apply_equity_tilt(usable, tilt_risk_on, max_per_asset_class)

    portfolio = _select_portfolio(
        selection_universe,
        start_idx_by_symbol,
        portfolio_size,
        allow_short,
        initial_capital,
        commission_bps,
        min_confidence_pct,
        include_earnings,
        include_news,
        selection_cap,
        short_confidence_premium,
    )
    if not portfolio:
        raise ValueError(
            "No se encontraron símbolos con señal BUY"
            + (" o SELL" if allow_short else "")
            + f" con al menos {min_confidence_pct}% de confianza antes de la fecha de inicio. "
            "Prueba con otro universo, fecha, un umbral de confianza más bajo, o habilita posiciones cortas."
        )

    if risk_parity_sizing:
        weights = _risk_parity_weights(portfolio)
    else:
        weights = {c["symbol"]: 1.0 / len(portfolio) for c in portfolio}
    capital_by_symbol = {symbol: round(initial_capital * weight, 2) for symbol, weight in weights.items()}

    per_symbol_results = [
        _walk_forward_result(
            usable[c["symbol"]],
            start_idx_by_symbol[c["symbol"]],
            c["symbol"],
            allow_short,
            capital_by_symbol[c["symbol"]],
            commission_bps,
            step,
            min_confidence_pct,
            adaptive_learning,
            stop_loss_pct,
            short_confidence_premium,
            risk_regime_sizing,
        )
        for c in portfolio
    ]

    portfolio_equity_curve = _combine_equity_curves(per_symbol_results, capital_by_symbol)
    final_equity = round(float(portfolio_equity_curve.iloc[-1]), 2)
    num_trading_days = max(len(r["equity_curve"]) for r in per_symbol_results)
    all_trades = [trade for r in per_symbol_results for trade in r["trades"]]
    benchmark = _buy_hold_benchmark(usable, start_idx_by_symbol, capital_by_symbol, commission_bps)

    return {
        "start_date": start_date,
        "end_date": str(portfolio_equity_curve.index[-1].date()),
        "num_trading_days": num_trading_days,
        "initial_capital": initial_capital,
        "capital_by_symbol": capital_by_symbol,
        "portfolio": portfolio,
        "final_equity": final_equity,
        "total_pnl_amount": round(final_equity - initial_capital, 2),
        "total_return_pct": round((final_equity / initial_capital - 1) * 100, 2),
        "risk_regime_sizing": risk_regime_sizing,
        "equity_regime_tilt": equity_regime_tilt,
        "equity_risk_on_at_start": tilt_risk_on,
        "per_symbol": [
            {
                "symbol": r["symbol"],
                "final_equity": round(float(r["equity_curve"].iloc[-1]), 2),
                "pnl_amount": round(float(r["equity_curve"].iloc[-1]) - capital_by_symbol[r["symbol"]], 2),
                "metrics": r["metrics"],
                "trades": r["trades"],
                "hindsight_summary": r["hindsight_summary"],
                "risk_regime_avg_exposure_pct": r["risk_regime_avg_exposure_pct"],
            }
            for r in per_symbol_results
        ],
        "portfolio_equity_curve": [
            {"date": str(d.date()), "equity": round(float(v), 2)} for d, v in portfolio_equity_curve.items()
        ],
        "hindsight_summary": hindsight_summary(all_trades),
        "benchmark_buy_hold": benchmark,
        "vs_benchmark_pct_points": round(
            (final_equity / initial_capital - 1) * 100 - benchmark["total_return_pct"], 2
        ),
        "errors": errors,
        "disclaimer": DISCLAIMER,
    }


def _run_rebalanced_simulation(
    dfs: dict[str, pd.DataFrame],
    start_date: str,
    end_date: str | None,
    portfolio_size: int,
    initial_capital: float,
    commission_bps: float | None,
    allow_short: bool,
    step: int,
    errors: dict[str, str],
    min_confidence_pct: float,
    adaptive_learning: bool,
    include_earnings: bool,
    include_news: bool,
    max_per_asset_class: int | None,
    risk_parity_sizing: bool,
    stop_loss_pct: float | None,
    short_confidence_premium: float,
    risk_regime_sizing: bool,
    rebalance_months: int,
    equity_regime_tilt: bool = False,
) -> dict:
    """Same day-by-day walk-forward, but instead of marrying the portfolio
    chosen on day one for the whole period, the selection is redone every
    `rebalance_months` calendar months — using, as always, only data
    available up to that boundary (each segment's dataframes are truncated
    at the *next* boundary, so neither selection nor walk-forward can peek
    past their own segment). The capital that comes out of one segment is
    what goes into the next.

    Honesty details that keep this from flattering itself:

    - Rotation isn't free: at every boundary after the first, each incoming
      symbol's allocation is charged twice its per-trade commission (exit
      the old book + enter the new one) — even if the model happened to be
      sitting in cash, because overestimating costs is the safe direction
      to be wrong in.
    - The earnings/news overlays are only ever applied to the *first*
      selection (and only if requested): Finnhub/Alpha Vantage return data
      relative to the real clock, so applying them at a historical
      rebalance boundary would leak today's information into a past-dated
      decision — the same lookahead rule the daily walk-forward follows.
    - A boundary where no candidate clears the confidence bar puts the
      whole portfolio in cash for that segment (capital unchanged) rather
      than forcing a pick; only an empty *first* selection raises, matching
      the non-rebalanced simulator.
    - Adaptive learning's hindsight window restarts with each segment (each
      segment is its own walk-forward call); it never reaches across a
      rebalance into another symbol's history."""
    if end_date:
        dfs = {symbol: df[df.index <= pd.Timestamp(end_date)] for symbol, df in dfs.items()}
    non_empty = {s: df for s, df in dfs.items() if len(df)}
    if not non_empty:
        raise ValueError("No hay datos disponibles para ningún símbolo.")
    last_date = max(df.index[-1] for df in non_empty.values())

    boundaries = [pd.Timestamp(start_date)]
    while boundaries[-1] + pd.DateOffset(months=rebalance_months) <= last_date:
        boundaries.append(boundaries[-1] + pd.DateOffset(months=rebalance_months))

    # Same "insufficient history at the overall start" bookkeeping as the
    # non-rebalanced path — relative to the overall start date, so the
    # errors dict means the same thing in both modes.
    overall_start_idx = {symbol: _find_start_index(df, start_date) for symbol, df in non_empty.items()}
    for symbol in dfs:
        if symbol not in non_empty or not (MIN_WARMUP_BARS <= overall_start_idx[symbol] < len(non_empty[symbol]) - 1):
            errors.setdefault(
                symbol,
                "Historial insuficiente antes de la fecha de inicio, o no hay barras después de esa fecha.",
            )

    capital = initial_capital
    segments = []
    curves = []
    all_trades = []
    initial_portfolio = None
    initial_capital_by_symbol = None

    for k, boundary in enumerate(boundaries):
        seg_end = boundaries[k + 1] if k + 1 < len(boundaries) else None
        seg_dfs = {
            symbol: (df[df.index < seg_end] if seg_end is not None else df)
            for symbol, df in non_empty.items()
        }
        start_idx_by_symbol = {symbol: _find_start_index(df, str(boundary.date())) for symbol, df in seg_dfs.items()}
        usable = {
            symbol: df
            for symbol, df in seg_dfs.items()
            if MIN_WARMUP_BARS <= start_idx_by_symbol[symbol] < len(df) - 1
        }

        tilt_risk_on = _equity_risk_on(usable, start_idx_by_symbol) if equity_regime_tilt else None
        selection_universe, selection_cap = _apply_equity_tilt(usable, tilt_risk_on, max_per_asset_class)

        portfolio = _select_portfolio(
            selection_universe,
            start_idx_by_symbol,
            portfolio_size,
            allow_short,
            capital,
            commission_bps,
            min_confidence_pct,
            include_earnings and k == 0,
            include_news and k == 0,
            selection_cap,
            short_confidence_premium,
        )
        if k == 0 and not portfolio:
            raise ValueError(
                "No se encontraron símbolos con señal BUY"
                + (" o SELL" if allow_short else "")
                + f" con al menos {min_confidence_pct}% de confianza antes de la fecha de inicio. "
                "Prueba con otro universo, fecha, un umbral de confianza más bajo, o habilita posiciones cortas."
            )

        segment = {"start_date": str(boundary.date()), "capital_start": round(capital, 2)}
        if equity_regime_tilt:
            segment["equity_risk_on"] = tilt_risk_on

        if not portfolio:
            seg_dates = sorted({d for df in usable.values() for d in df.index[df.index >= boundary]})
            if seg_dates:
                curves.append(pd.Series(float(capital), index=pd.DatetimeIndex(seg_dates)))
                segment["end_date"] = str(seg_dates[-1].date())
            segment.update(
                {
                    "portfolio": [],
                    "capital_end": round(capital, 2),
                    "return_pct": 0.0,
                    "note": "Sin candidatos que superen el umbral de confianza — el segmento se pasa en efectivo.",
                }
            )
            segments.append(segment)
            continue

        if risk_parity_sizing:
            weights = _risk_parity_weights(portfolio)
        else:
            weights = {c["symbol"]: 1.0 / len(portfolio) for c in portfolio}
        capital_by_symbol = {}
        for symbol, weight in weights.items():
            allocation = capital * weight
            if k > 0:
                bps = commission_bps if commission_bps is not None else default_commission_bps(symbol)
                allocation *= 1 - 2 * bps / 10000  # rotation cost: exit old + enter new
            capital_by_symbol[symbol] = round(allocation, 2)

        per_symbol_results = [
            _walk_forward_result(
                usable[c["symbol"]],
                start_idx_by_symbol[c["symbol"]],
                c["symbol"],
                allow_short,
                capital_by_symbol[c["symbol"]],
                commission_bps,
                step,
                min_confidence_pct,
                adaptive_learning,
                stop_loss_pct,
                short_confidence_premium,
                risk_regime_sizing,
            )
            for c in portfolio
        ]
        seg_curve = _combine_equity_curves(per_symbol_results, capital_by_symbol)
        seg_final = float(seg_curve.iloc[-1])
        curves.append(seg_curve)
        for r in per_symbol_results:
            all_trades.extend(r["trades"])

        segment.update(
            {
                "end_date": str(seg_curve.index[-1].date()),
                "portfolio": [c["symbol"] for c in portfolio],
                "capital_by_symbol": capital_by_symbol,
                "capital_end": round(seg_final, 2),
                "return_pct": round((seg_final / capital - 1) * 100, 2),
                "per_symbol": [
                    {
                        "symbol": r["symbol"],
                        "final_equity": round(float(r["equity_curve"].iloc[-1]), 2),
                        "pnl_amount": round(float(r["equity_curve"].iloc[-1]) - capital_by_symbol[r["symbol"]], 2),
                        "num_trades": len(r["trades"]),
                        "risk_regime_avg_exposure_pct": r["risk_regime_avg_exposure_pct"],
                    }
                    for r in per_symbol_results
                ],
            }
        )
        segments.append(segment)

        if k == 0:
            initial_portfolio = portfolio
            initial_capital_by_symbol = capital_by_symbol
        capital = seg_final

    portfolio_equity_curve = pd.concat(curves)
    final_equity = round(float(capital), 2)

    # The passive yardstick stays the same as the non-rebalanced report:
    # the *initial* selection bought on day one and never touched — that's
    # what "doing nothing" actually means for the whole period.
    benchmark_dfs = {symbol: non_empty[symbol] for symbol in initial_capital_by_symbol}
    benchmark = _buy_hold_benchmark(benchmark_dfs, overall_start_idx, initial_capital_by_symbol, commission_bps)

    return {
        "start_date": start_date,
        "end_date": str(portfolio_equity_curve.index[-1].date()),
        "num_trading_days": len(portfolio_equity_curve),
        "initial_capital": initial_capital,
        "capital_by_symbol": initial_capital_by_symbol,
        "portfolio": initial_portfolio,
        "final_equity": final_equity,
        "total_pnl_amount": round(final_equity - initial_capital, 2),
        "total_return_pct": round((final_equity / initial_capital - 1) * 100, 2),
        "rebalance_months": rebalance_months,
        "segments": segments,
        "risk_regime_sizing": risk_regime_sizing,
        "equity_regime_tilt": equity_regime_tilt,
        "portfolio_equity_curve": [
            {"date": str(d.date()), "equity": round(float(v), 2)} for d, v in portfolio_equity_curve.items()
        ],
        "hindsight_summary": hindsight_summary(all_trades),
        "benchmark_buy_hold": benchmark,
        "vs_benchmark_pct_points": round(
            (final_equity / initial_capital - 1) * 100 - benchmark["total_return_pct"], 2
        ),
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
    allow_short: bool = False,
    step: int = 1,
    min_confidence_pct: float = 55.0,
    adaptive_learning: bool = True,
    include_earnings: bool = False,
    include_news: bool = False,
    max_per_asset_class: int | None = DEFAULT_MAX_PER_ASSET_CLASS,
    risk_parity_sizing: bool = True,
    stop_loss_pct: float | None = DEFAULT_STOP_LOSS_PCT,
    short_confidence_premium: float = 0.0,
    risk_regime_sizing: bool = True,
    rebalance_months: int | None = 3,
    equity_regime_tilt: bool = False,
) -> dict:
    """Auto-selects a portfolio (from real symbols, defaulting to the full
    example universe) using only data before `start_date`, then walks
    forward day by day executing the ensemble recommendation's calls,
    reporting the combined dollar P&L over the period. `min_confidence_pct`
    is the minimum ensemble confidence required to select a symbol or flip
    its position on a given day — below it, a BUY/SELL call is treated as a
    HOLD, to avoid overtrading on weak/noisy signals. `adaptive_learning`
    additionally raises that bar on the fly based on the simulator's own
    recent hindsight track record (see `_walk_forward_result`).

    `include_earnings`/`include_news` nudge each candidate's confidence at
    *selection* time only (Finnhub/Alpha Vantage — real stock tickers only;
    see the module docstring for why they aren't applied inside the daily
    walk-forward). Selection always also weighs each candidate's own
    historical Sharpe ratio and max drawdown, regardless of these flags.
    `max_per_asset_class` caps how many picks can share an asset class
    (`None` to disable — see `_select_portfolio`). `risk_parity_sizing`
    sizes each position inversely to its own historical volatility instead
    of splitting capital equally (see `_risk_parity_weights`).
    `stop_loss_pct` is a hard per-position exit independent of the
    technical signal (`None` to disable — see `_walk_forward_result`).
    `risk_regime_sizing` scales position exposure down while short-term
    realized volatility runs above its longer-term baseline (see
    `_vol_regime_exposure`) — on by default: validated across 6 historical
    windows (incl. 2007-2010), it reduced max drawdown in 6/6 with a
    slightly positive average return delta (+1.17 pp; per-window returns
    were mixed, 3/6 — it trades a little upside in calm bull stretches for
    a smaller hit in turbulent ones). `rebalance_months` (default 3,
    `None` to disable) re-runs the portfolio selection every that many
    calendar months instead of holding day one's picks for the whole
    period — validated across 9 windows (6 tuning-era + 3 virgin):
    quarterly beat the no-rebalance model in 7/9 and beat buy & hold in
    6/9, the first configuration to do so broadly; the two losses were
    2004-2007 (the no-rebalance arm had happened to concentrate 100% in
    AAPL pre-iPhone — a fluke diversification is *supposed* to give up)
    and 2014-2017 (-1 pp). See `_run_rebalanced_simulation` for the
    no-lookahead and rotation-cost details. `equity_regime_tilt` (default
    off pending validation) narrows each (re)selection to stocks/indexes
    while the S&P 500 trades above its 200-bar moving average — see
    `_equity_risk_on`."""
    symbols = symbols or _default_symbols()

    dfs = {}
    errors = {}
    for symbol in symbols:
        try:
            dfs[symbol] = get_ohlcv(symbol, period=period, interval=interval)
        except Exception as exc:  # data provider/network failures are per-symbol, not fatal for the whole scan
            errors[symbol] = str(exc)

    return _run_simulation(
        dfs,
        start_date,
        end_date,
        portfolio_size,
        initial_capital,
        commission_bps,
        allow_short,
        step,
        errors,
        min_confidence_pct,
        adaptive_learning,
        include_earnings,
        include_news,
        max_per_asset_class,
        risk_parity_sizing,
        stop_loss_pct,
        short_confidence_premium,
        risk_regime_sizing,
        rebalance_months,
        equity_regime_tilt,
    )


def simulate_portfolio_synthetic(
    start_date: str = "2026-01-01",
    end_date: str | None = None,
    profiles: list[dict] | None = None,
    portfolio_size: int = 5,
    seed: int = 42,
    initial_capital: float = 10_000.0,
    commission_bps: float | None = None,
    allow_short: bool = False,
    step: int = 1,
    min_confidence_pct: float = 55.0,
    adaptive_learning: bool = True,
    include_earnings: bool = False,
    include_news: bool = False,
    max_per_asset_class: int | None = None,
    risk_parity_sizing: bool = True,
    stop_loss_pct: float | None = DEFAULT_STOP_LOSS_PCT,
    short_confidence_premium: float = 0.0,
    risk_regime_sizing: bool = True,
    rebalance_months: int | None = 3,
    equity_regime_tilt: bool = False,
) -> dict:
    """Same simulation, but over synthetic profiles reaching into 2026 —
    usable with no network access. Real dates only line up exactly with
    `DEFAULT_PORTFOLIO_PROFILES` (~3 years of synthetic warmup ending right
    around 2026-01-01); custom `profiles` need their own `start_date` picked
    so the requested `start_date` actually falls inside the generated range.

    `include_earnings`/`include_news` still call out to Finnhub/Alpha
    Vantage for these (fake) profile labels, so — same as
    `app.opportunities`'s synthetic path — they'll come back "unavailable"
    rather than do anything useful; the risk-adjusted (Sharpe/drawdown)
    selection still applies regardless. `max_per_asset_class` defaults to
    `None` (disabled) here, unlike the real-data path: synthetic labels like
    "Símbolo A (tendencia alcista)" carry no real ticker convention, so
    `infer_asset_class` falls back to treating every one of them as
    the same class — capping picks per class would silently shrink any
    demo portfolio bigger than the cap. Pass a specific value to test the
    cap's mechanics against a controlled scenario."""
    profiles = profiles or DEFAULT_PORTFOLIO_PROFILES

    dfs = {
        profile["label"]: generate_ohlcv(regimes=profile["regimes"], start_date=_SYNTHETIC_START_DATE, seed=seed)
        for profile in profiles
    }
    return _run_simulation(
        dfs,
        start_date,
        end_date,
        portfolio_size,
        initial_capital,
        commission_bps,
        allow_short,
        step,
        {},
        min_confidence_pct,
        adaptive_learning,
        include_earnings,
        include_news,
        max_per_asset_class,
        risk_parity_sizing,
        stop_loss_pct,
        short_confidence_premium,
        risk_regime_sizing,
        rebalance_months,
        equity_regime_tilt,
    )
