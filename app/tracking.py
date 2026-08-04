"""Forward signal tracking: log each day's opportunity-scan calls, then
grade them later against what prices actually did.

Every validation elsewhere in this project is a backtest — computed after
the fact, on windows that were also used to tune the model, so each new
improvement "validated" there carries a growing overfitting risk. This
module builds the only kind of evidence immune to that: signals written
down *before* the outcome existed. Log the daily scan, wait, then ask how
the calls actually did. A model that looks great in backtests and mediocre
in its own forward log is overfit; this file is where that verdict
accumulates.

The log is a plain JSONL file meant to be committed to the repository —
the sessions that write it run in ephemeral containers, so an uncommitted
log dies with the container.
"""

from __future__ import annotations

import json
import os

import pandas as pd

from app.data.providers import get_ohlcv

DEFAULT_LOG_PATH = "signals_log.jsonl"
DEFAULT_HORIZON_BARS = 10


def log_scan(report: dict, path: str = DEFAULT_LOG_PATH) -> dict:
    """Appends the scan's BUY/SELL calls to the JSONL log, one line per scan
    date. The scan date comes from the entries' own `as_of` (the last bar the
    recommendation saw), not the wall clock — rerunning the scan twice on the
    same market day is deduplicated instead of double-logged."""
    entries = report.get("top_buy", []) + report.get("top_sell", [])
    if not entries:
        return {"logged": False, "reason": "El escaneo no trajo señales BUY/SELL que registrar."}

    as_of = str(entries[0]["as_of"])[:10]

    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip() and json.loads(line).get("as_of") == as_of:
                    return {"logged": False, "reason": f"Ya hay señales registradas para {as_of}.", "as_of": as_of}

    record = {
        "as_of": as_of,
        "signals": [
            {
                "symbol": e["symbol"],
                "action": e["overall_action"],
                "confidence_pct": e["confidence_pct"],
                "last_close": e.get("last_close"),
            }
            for e in entries
        ],
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {"logged": True, "as_of": as_of, "num_signals": len(record["signals"])}


def _load_log(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def evaluate_signals(
    path: str = DEFAULT_LOG_PATH,
    horizon_bars: int = DEFAULT_HORIZON_BARS,
    period: str = "1y",
) -> dict:
    """Grades every logged signal that already has `horizon_bars` of market
    history after it: a BUY hits if the close `horizon_bars` bars later is
    above the close on the signal date, a SELL hits if it's below. Signals
    too recent to grade come back as `pending`. Data failures are reported
    per symbol, never silently dropped."""
    records = _load_log(path)
    if not records:
        return {"num_scans": 0, "graded": [], "pending": [], "errors": {}, "summary": None}

    symbols = sorted({s["symbol"] for r in records for s in r["signals"]})
    dfs = {}
    errors = {}
    for symbol in symbols:
        try:
            dfs[symbol] = get_ohlcv(symbol, period=period)
        except Exception as exc:
            errors[symbol] = str(exc)

    graded = []
    pending = []
    for record in records:
        for signal in record["signals"]:
            symbol = signal["symbol"]
            if symbol not in dfs:
                continue
            df = dfs[symbol]
            idx = int(df.index.searchsorted(pd.Timestamp(record["as_of"])))
            if idx >= len(df):
                pending.append({**signal, "as_of": record["as_of"], "reason": "fecha fuera del historial traído"})
                continue
            if idx + horizon_bars >= len(df):
                pending.append({**signal, "as_of": record["as_of"], "reason": "aún no pasan suficientes días de mercado"})
                continue
            entry_close = float(df["Close"].iloc[idx])
            later_close = float(df["Close"].iloc[idx + horizon_bars])
            forward_return_pct = round((later_close / entry_close - 1) * 100, 2)
            hit = forward_return_pct > 0 if signal["action"] == "BUY" else forward_return_pct < 0
            graded.append(
                {
                    **signal,
                    "as_of": record["as_of"],
                    "forward_return_pct": forward_return_pct,
                    "hit": hit,
                }
            )

    def _side_summary(side: str) -> dict | None:
        side_signals = [g for g in graded if g["action"] == side]
        if not side_signals:
            return None
        return {
            "num": len(side_signals),
            "hit_rate_pct": round(sum(1 for g in side_signals if g["hit"]) / len(side_signals) * 100, 1),
            "avg_forward_return_pct": round(
                sum(g["forward_return_pct"] for g in side_signals) / len(side_signals), 2
            ),
        }

    summary = None
    if graded:
        summary = {
            "num_graded": len(graded),
            "hit_rate_pct": round(sum(1 for g in graded if g["hit"]) / len(graded) * 100, 1),
            "buy": _side_summary("BUY"),
            "sell": _side_summary("SELL"),
            "horizon_bars": horizon_bars,
        }

    return {
        "num_scans": len(records),
        "graded": graded,
        "pending": pending,
        "errors": errors,
        "summary": summary,
    }
