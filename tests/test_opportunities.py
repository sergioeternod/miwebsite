import app.opportunities as opportunities_module
from app.opportunities import find_opportunities_real, find_opportunities_synthetic


def test_find_opportunities_synthetic_end_to_end():
    report = find_opportunities_synthetic()
    assert report["evaluated"] == 5
    assert not report["errors"]
    assert len(report["top_buy"]) <= 5
    assert len(report["top_sell"]) <= 5
    for entry in report["top_buy"]:
        assert entry["overall_action"] == "BUY"
    for entry in report["top_sell"]:
        assert entry["overall_action"] == "SELL"


def test_find_opportunities_synthetic_sorted_by_confidence_desc():
    report = find_opportunities_synthetic()
    confidences = [e["confidence_pct"] for e in report["top_buy"]]
    assert confidences == sorted(confidences, reverse=True)


def test_find_opportunities_synthetic_top_n_limits_results():
    report = find_opportunities_synthetic(top_n=1)
    assert len(report["top_buy"]) <= 1
    assert len(report["top_sell"]) <= 1


def test_find_opportunities_entries_drop_verbose_fields():
    report = find_opportunities_synthetic()
    for entry in report["top_buy"] + report["top_sell"]:
        assert "per_strategy" not in entry
        assert "disclaimer" not in entry
        assert "symbol" in entry
        assert "confidence_pct" in entry


def test_find_opportunities_real_records_per_symbol_failures_without_crashing(monkeypatch, random_walk_df):
    def fake_get_ohlcv(symbol, period="2y", interval="1d"):
        if symbol == "BROKEN":
            raise RuntimeError("network unreachable")
        return random_walk_df

    monkeypatch.setattr(opportunities_module, "get_ohlcv", fake_get_ohlcv)
    report = find_opportunities_real(["OK", "BROKEN"])

    assert report["evaluated"] == 1
    assert "BROKEN" in report["errors"]
    assert "network unreachable" in report["errors"]["BROKEN"]


def test_find_opportunities_real_defaults_to_example_universe(monkeypatch, random_walk_df):
    seen_symbols = []

    def fake_get_ohlcv(symbol, period="2y", interval="1d"):
        seen_symbols.append(symbol)
        return random_walk_df

    monkeypatch.setattr(opportunities_module, "get_ohlcv", fake_get_ohlcv)
    find_opportunities_real()

    assert len(seen_symbols) > 10
    assert "AAPL" in seen_symbols


def test_find_opportunities_includes_earnings_and_news_when_requested(monkeypatch, random_walk_df):
    # This test is about the overlay *wiring*, not the ensemble's mood on the
    # fixture — pin recommend() to a BUY so the entry reliably exists no
    # matter how the real strategies read the random walk.
    monkeypatch.setattr(opportunities_module, "get_ohlcv", lambda symbol, period="2y", interval="1d": random_walk_df)
    monkeypatch.setattr(
        opportunities_module,
        "recommend",
        lambda df, symbol="", **k: {"symbol": symbol, "overall_action": "BUY", "confidence_pct": 80.0},
    )
    monkeypatch.setattr(
        opportunities_module,
        "apply_earnings_overlay",
        lambda result, symbol: {**result, "earnings": {"available": False, "reason": "sin key"}},
    )
    monkeypatch.setattr(
        opportunities_module,
        "apply_news_overlay",
        lambda result, symbol: {**result, "news": {"available": False, "reason": "sin key"}},
    )
    report = find_opportunities_real(["OK"], include_earnings=True, include_news=True)
    entries = report["top_buy"] + report["top_sell"]
    assert entries, "expected at least one BUY or SELL entry from the pinned recommendation"
    assert all("earnings" in e and "news" in e for e in entries)


def test_find_opportunities_omits_overlays_when_not_requested(monkeypatch, random_walk_df):
    monkeypatch.setattr(opportunities_module, "get_ohlcv", lambda symbol, period="2y", interval="1d": random_walk_df)
    report = find_opportunities_real(["OK"])
    entries = report["top_buy"] + report["top_sell"]
    for entry in entries:
        assert "earnings" not in entry
        assert "news" not in entry
