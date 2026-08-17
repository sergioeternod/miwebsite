import pandas as pd
import pytest

import app.fundamentals.valuation_history as vh_module
from app.data.edgar_client import parse_quarterly_eps, trailing_eps_known_at
from app.fundamentals.valuation import combine_tilts, guidance_tilt
from app.fundamentals.valuation_history import apply_pe_history_tilt


def _entry(start, end, filed, val):
    return {"start": start, "end": end, "filed": filed, "val": val}


QUARTERS_2023 = [
    _entry("2023-01-01", "2023-03-31", "2023-05-01", 1.0),
    _entry("2023-04-01", "2023-06-30", "2023-08-01", 1.1),
    _entry("2023-07-01", "2023-09-30", "2023-11-01", 1.2),
]
ANNUAL_2023 = _entry("2023-01-01", "2023-12-31", "2024-02-15", 5.0)


def test_parse_derives_fiscal_q4_from_annual():
    quarters = parse_quarterly_eps(QUARTERS_2023 + [ANNUAL_2023])
    assert len(quarters) == 4
    q4 = quarters[-1]
    assert q4["end"] == "2023-12-31"
    assert q4["filed"] == "2024-02-15"  # se conoce cuando se presenta el 10-K
    assert q4["eps"] == pytest.approx(5.0 - 3.3)


def test_parse_keeps_earliest_filing_for_restated_periods():
    restated = _entry("2023-01-01", "2023-03-31", "2024-02-15", 0.9)  # re-expresado después
    quarters = parse_quarterly_eps(QUARTERS_2023 + [restated])
    q1 = next(q for q in quarters if q["end"] == "2023-03-31")
    assert q1["eps"] == 1.0  # el valor conocido primero, no la re-expresión


def test_trailing_eps_is_gated_by_filing_date():
    quarters = parse_quarterly_eps(QUARTERS_2023 + [ANNUAL_2023])
    # Antes del 10-K solo hay 3 trimestres públicos -> sin TTM.
    assert trailing_eps_known_at(quarters, "2024-02-14") is None
    # El día del 10-K los 4 trimestres son públicos.
    assert trailing_eps_known_at(quarters, "2024-02-15") == pytest.approx(5.0)


def test_trailing_eps_rejects_stale_gaps():
    old = [
        _entry("2020-01-01", "2020-03-31", "2020-05-01", 1.0),
        _entry("2020-04-01", "2020-06-30", "2020-08-01", 1.0),
    ]
    recent = [
        _entry("2023-01-01", "2023-03-31", "2023-05-01", 1.0),
        _entry("2023-04-01", "2023-06-30", "2023-08-01", 1.0),
    ]
    quarters = parse_quarterly_eps(old + recent)
    assert trailing_eps_known_at(quarters, "2024-01-01") is None  # 4 trimestres pero con hueco de años


def _window(price=100.0, days=250):
    idx = pd.date_range("2024-01-01", periods=days, freq="D")
    return pd.DataFrame({"Close": [price] * days}, index=idx)


def test_apply_pe_history_tilt_dampens_expensive_buy(monkeypatch):
    monkeypatch.setattr(vh_module, "get_quarterly_eps", lambda s: parse_quarterly_eps(QUARTERS_2023 + [ANNUAL_2023]))
    monkeypatch.setattr(vh_module, "get_split_events", lambda s: [])
    vh_module._adjusted_cache.clear()
    rec = apply_pe_history_tilt({"overall_action": "BUY", "confidence_pct": 90.0}, "AAPL", _window(price=250.0))
    # P/E = 250 / 5.0 = 50 -> cara -> contradice el BUY
    assert rec["confidence_pct"] < 90.0
    assert rec["pe_history"]["trailing_pe"] == pytest.approx(50.0)
    assert rec["pe_history"]["alignment_with_technical_signal"] == "contradice"
    assert rec["overall_action"] == "BUY"


def test_apply_pe_history_tilt_noop_for_non_stock_and_missing_data(monkeypatch):
    rec = apply_pe_history_tilt({"overall_action": "BUY", "confidence_pct": 90.0}, "^GSPC", _window())
    assert rec["confidence_pct"] == 90.0
    assert rec["pe_history"]["applicable"] is False

    from app.data.edgar_client import EdgarUnavailableError

    def boom(sym):
        raise EdgarUnavailableError("sin red")

    monkeypatch.setattr(vh_module, "get_quarterly_eps", boom)
    monkeypatch.setattr(vh_module, "get_split_events", lambda s: [])
    vh_module._adjusted_cache.clear()
    rec2 = apply_pe_history_tilt({"overall_action": "BUY", "confidence_pct": 90.0}, "AAPL", _window())
    assert rec2["confidence_pct"] == 90.0
    assert rec2["pe_history"]["applicable"] is False


def test_guidance_tilt_directions():
    up = {"0y": {"eps_avg": 10.5, "eps_avg_90d_ago": 10.0}, "+1y": {"eps_avg": 11.5, "eps_avg_90d_ago": 11.0}}
    down = {"0y": {"eps_avg": 9.5, "eps_avg_90d_ago": 10.0}, "+1y": {"eps_avg": 10.4, "eps_avg_90d_ago": 11.0}}
    mixed = {"0y": {"eps_avg": 10.5, "eps_avg_90d_ago": 10.0}, "+1y": {"eps_avg": 10.4, "eps_avg_90d_ago": 11.0}}
    assert guidance_tilt(up)["signal"] == "bullish"
    assert guidance_tilt(down)["signal"] == "bearish"
    assert guidance_tilt(mixed)["signal"] == "neutral"
    assert guidance_tilt({})["signal"] == "neutral"


def test_combine_tilts_opposing_readings_partially_cancel():
    band = {"signal": "bullish", "confidence_tilt_pct": 5.0, "rationale": "barata."}
    guidance = {"signal": "bearish", "confidence_tilt_pct": 3.0, "rationale": "revisiones a la baja."}
    combined = combine_tilts(band, guidance)
    assert combined["signal"] == "bullish"
    assert combined["confidence_tilt_pct"] == pytest.approx(2.0)


def test_selection_applies_pe_tilt_only_when_enabled(monkeypatch):
    import numpy as np

    import app.portfolio as portfolio_module
    from app.portfolio import _select_portfolio

    calls = []

    def recorder(rec, symbol, window):
        calls.append(symbol)
        return rec

    monkeypatch.setattr(portfolio_module, "apply_pe_history_tilt", recorder)
    monkeypatch.setattr(
        portfolio_module, "recommend", lambda *a, **k: {"overall_action": "BUY", "confidence_pct": 80.0}
    )
    close = pd.Series(np.linspace(100, 300, 400))
    df = pd.DataFrame({"Open": close, "High": close, "Low": close, "Close": close, "Volume": 1000})
    df.index = pd.date_range("2023-01-01", periods=len(df), freq="D")
    dfs = {"AAPL": df}

    _select_portfolio(dfs, {"AAPL": 300}, 1, False, 10_000.0, None, 55.0)
    assert calls == []
    _select_portfolio(dfs, {"AAPL": 300}, 1, False, 10_000.0, None, 55.0, fundamental_pe_tilt=True)
    assert calls == ["AAPL"]


def test_split_adjustment_restates_old_eps_into_todays_units(monkeypatch):
    monkeypatch.setattr(vh_module, "get_quarterly_eps", lambda s: parse_quarterly_eps(QUARTERS_2023 + [ANNUAL_2023]))
    monkeypatch.setattr(vh_module, "get_split_events", lambda s: [{"date": "2024-06-01", "ratio": 4.0}])
    vh_module._adjusted_cache.clear()
    # Split 4:1 posterior a todos los trimestres: TTM 5.0 -> 1.25 en unidades de hoy.
    pe = vh_module.pe_known_at("AAPL", 25.0, "2024-07-01")
    assert pe == pytest.approx(25.0 / 1.25)
    vh_module._adjusted_cache.clear()
