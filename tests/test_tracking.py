import json

import numpy as np
import pandas as pd
import pytest

import app.tracking as tracking_module
from app.tracking import evaluate_signals, log_scan


def _scan_report(as_of="2026-08-04", buy_symbol="AAPL", sell_symbol="TSLA"):
    return {
        "top_buy": [
            {"symbol": buy_symbol, "overall_action": "BUY", "confidence_pct": 90.0, "as_of": f"{as_of} 00:00:00", "last_close": 100.0}
        ],
        "top_sell": [
            {"symbol": sell_symbol, "overall_action": "SELL", "confidence_pct": 85.0, "as_of": f"{as_of} 00:00:00", "last_close": 200.0}
        ],
    }


def _ohlcv(closes, start="2026-08-04"):
    close = pd.Series(np.array(closes, dtype=float))
    df = pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close, "Volume": 1000})
    df.index = pd.date_range(start, periods=len(df), freq="D")
    df.index.name = "Date"
    return df


def test_log_scan_appends_and_dedupes(tmp_path):
    path = str(tmp_path / "signals.jsonl")

    first = log_scan(_scan_report(), path=path)
    assert first["logged"] is True
    assert first["num_signals"] == 2

    duplicate = log_scan(_scan_report(), path=path)
    assert duplicate["logged"] is False

    other_day = log_scan(_scan_report(as_of="2026-08-05"), path=path)
    assert other_day["logged"] is True

    with open(path) as f:
        lines = [json.loads(l) for l in f if l.strip()]
    assert [l["as_of"] for l in lines] == ["2026-08-04", "2026-08-05"]


def test_log_scan_empty_report(tmp_path):
    result = log_scan({"top_buy": [], "top_sell": []}, path=str(tmp_path / "s.jsonl"))
    assert result["logged"] is False


def test_evaluate_signals_grades_hits_and_misses(tmp_path, monkeypatch):
    path = str(tmp_path / "signals.jsonl")
    log_scan(_scan_report(), path=path)

    # AAPL (BUY) rises 100 -> 110 over the horizon: hit.
    # TSLA (SELL) also rises 200 -> 220: miss.
    dfs = {
        "AAPL": _ohlcv([100 + i for i in range(15)]),
        "TSLA": _ohlcv([200 + 2 * i for i in range(15)]),
    }
    monkeypatch.setattr(tracking_module, "get_ohlcv", lambda symbol, period="1y": dfs[symbol])

    result = evaluate_signals(path=path, horizon_bars=10)
    graded = {g["symbol"]: g for g in result["graded"]}
    assert graded["AAPL"]["hit"] is True
    assert graded["AAPL"]["forward_return_pct"] == pytest.approx(10.0)
    assert graded["TSLA"]["hit"] is False
    assert result["summary"]["num_graded"] == 2
    assert result["summary"]["hit_rate_pct"] == 50.0
    assert result["summary"]["buy"]["hit_rate_pct"] == 100.0
    assert result["summary"]["sell"]["hit_rate_pct"] == 0.0


def test_evaluate_signals_marks_recent_signals_pending(tmp_path, monkeypatch):
    path = str(tmp_path / "signals.jsonl")
    log_scan(_scan_report(), path=path)

    # Only 5 bars of history after the signal: not enough for a 10-bar horizon.
    dfs = {"AAPL": _ohlcv([100, 101, 102, 103, 104]), "TSLA": _ohlcv([200, 199, 198, 197, 196])}
    monkeypatch.setattr(tracking_module, "get_ohlcv", lambda symbol, period="1y": dfs[symbol])

    result = evaluate_signals(path=path, horizon_bars=10)
    assert result["graded"] == []
    assert len(result["pending"]) == 2
    assert result["summary"] is None


def test_evaluate_signals_reports_fetch_errors(tmp_path, monkeypatch):
    path = str(tmp_path / "signals.jsonl")
    log_scan(_scan_report(), path=path)

    def flaky_get_ohlcv(symbol, period="1y"):
        if symbol == "TSLA":
            raise RuntimeError("network down")
        return _ohlcv([100 + i for i in range(15)])

    monkeypatch.setattr(tracking_module, "get_ohlcv", flaky_get_ohlcv)
    result = evaluate_signals(path=path, horizon_bars=10)
    assert "TSLA" in result["errors"]
    assert [g["symbol"] for g in result["graded"]] == ["AAPL"]


def test_evaluate_signals_empty_log(tmp_path):
    result = evaluate_signals(path=str(tmp_path / "missing.jsonl"))
    assert result["num_scans"] == 0
    assert result["summary"] is None
