import pytest

import app.fundamentals.valuation as valuation_module
from app.data.yahoo_quote_client import QuoteSummaryUnavailableError
from app.fundamentals.valuation import (
    CHEAP_PE_MAX,
    EXPENSIVE_PE_MIN,
    MAX_CONFIDENCE_TILT_PCT,
    apply_valuation_overlay,
    valuation_report,
    valuation_tilt,
)


def test_tilt_cheap_pe_is_bullish():
    tilt = valuation_tilt(trailing_pe=10.0, forward_pe=None)
    assert tilt["signal"] == "bullish"
    assert 0 < tilt["confidence_tilt_pct"] <= MAX_CONFIDENCE_TILT_PCT


def test_tilt_expensive_pe_is_bearish_and_caps():
    tilt = valuation_tilt(trailing_pe=45.0, forward_pe=None)
    assert tilt["signal"] == "bearish"
    extreme = valuation_tilt(trailing_pe=500.0, forward_pe=None)
    assert extreme["confidence_tilt_pct"] == MAX_CONFIDENCE_TILT_PCT


def test_tilt_neutral_band_and_missing_pe():
    assert valuation_tilt(20.0, None)["signal"] == "neutral"
    assert valuation_tilt(20.0, None)["confidence_tilt_pct"] == 0.0
    assert valuation_tilt(None, None)["signal"] == "neutral"
    assert valuation_tilt(-8.0, None)["signal"] == "neutral"  # pérdidas: sin P/E utilizable
    assert valuation_tilt(CHEAP_PE_MAX, None)["signal"] == "neutral"
    assert valuation_tilt(EXPENSIVE_PE_MIN, None)["signal"] == "neutral"


def test_report_not_applicable_for_non_stocks():
    report = valuation_report("^GSPC")
    assert report["applicable"] is False
    assert report["confidence_tilt_pct"] == 0.0
    report_fx = valuation_report("EURUSD=X")
    assert report_fx["applicable"] is False


def test_overlay_expensive_pe_dampens_buy(monkeypatch):
    monkeypatch.setattr(
        valuation_module, "get_valuation_metrics",
        lambda symbol: {"trailing_pe": 60.0, "forward_pe": None, "trailing_eps": 5.0},
    )
    rec = {"overall_action": "BUY", "confidence_pct": 90.0}
    out = apply_valuation_overlay(rec, "AAPL")
    assert out["confidence_pct"] < 90.0
    assert out["valuation"]["alignment_with_technical_signal"] == "contradice"
    assert out["overall_action"] == "BUY"  # nunca cambia la acción


def test_overlay_expensive_pe_reinforces_sell(monkeypatch):
    monkeypatch.setattr(
        valuation_module, "get_valuation_metrics",
        lambda symbol: {"trailing_pe": 60.0, "forward_pe": None, "trailing_eps": 5.0},
    )
    out = apply_valuation_overlay({"overall_action": "SELL", "confidence_pct": 80.0}, "AAPL")
    assert out["confidence_pct"] > 80.0
    assert out["valuation"]["alignment_with_technical_signal"] == "refuerza"


def test_overlay_neutral_band_changes_nothing(monkeypatch):
    monkeypatch.setattr(
        valuation_module, "get_valuation_metrics",
        lambda symbol: {"trailing_pe": 22.0, "forward_pe": 20.0, "trailing_eps": 5.0},
    )
    out = apply_valuation_overlay({"overall_action": "BUY", "confidence_pct": 88.0}, "AAPL")
    assert out["confidence_pct"] == 88.0
    assert out["valuation"]["confidence_adjustment_pct"] == 0.0


def test_overlay_degrades_gracefully(monkeypatch):
    def boom(symbol):
        raise QuoteSummaryUnavailableError("sin red")

    monkeypatch.setattr(valuation_module, "get_valuation_metrics", boom)
    out = apply_valuation_overlay({"overall_action": "BUY", "confidence_pct": 88.0}, "AAPL")
    assert out["confidence_pct"] == 88.0
    assert out["valuation"]["available"] is False


def test_overlay_non_stock_is_noop_without_fetch(monkeypatch):
    def boom(symbol):
        raise AssertionError("no debe consultar datos para clases sin P/E")

    monkeypatch.setattr(valuation_module, "get_valuation_metrics", boom)
    out = apply_valuation_overlay({"overall_action": "BUY", "confidence_pct": 88.0}, "BTC-USD")
    assert out["confidence_pct"] == 88.0
    assert out["valuation"]["applicable"] is False


def test_sector_relative_reading_thresholds():
    from app.fundamentals.sector_pe import relative_reading

    assert relative_reading(20.0, 30.0)["reading"] == "barata para su industria"  # 0.67x
    assert relative_reading(30.0, 30.0)["reading"] == "en línea con su industria"
    assert relative_reading(45.0, 30.0)["reading"] == "cara para su industria"  # 1.5x
    assert relative_reading(None, 30.0)["reading"] == "sin referencia"
    assert relative_reading(20.0, None)["reading"] == "sin referencia"


def test_sector_reference_prefers_industry_over_sector():
    from app.fundamentals.sector_pe import reference_pe_for

    ref, label = reference_pe_for("Technology", "Semiconductors")
    assert (ref, label) == (28.0, "Semiconductors")
    ref2, label2 = reference_pe_for("Technology", "Industria Desconocida")
    assert (ref2, label2) == (27.0, "Technology")
    assert reference_pe_for(None, None) == (None, None)


def test_sector_relative_not_applicable_for_non_stocks():
    from app.fundamentals.sector_pe import sector_relative_valuation

    assert sector_relative_valuation("^GSPC", 25.0) == {"applicable": False}
