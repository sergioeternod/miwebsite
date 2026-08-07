import pytest

from app.config import AssetClass, DEFAULT_COMMISSION_BPS, default_commission_bps, infer_asset_class


@pytest.mark.parametrize(
    "symbol,expected",
    [
        ("AAPL", AssetClass.STOCK),
        ("MSFT", AssetClass.STOCK),
        ("BTC-USD", AssetClass.CRYPTO),
        ("ETH-USD", AssetClass.CRYPTO),
        ("SOL-USDT", AssetClass.CRYPTO),
        ("EURUSD=X", AssetClass.FOREX),
        ("USDJPY=X", AssetClass.FOREX),
        ("GC=F", AssetClass.COMMODITY),
        ("CL=F", AssetClass.COMMODITY),
        ("^GSPC", AssetClass.INDEX),
        ("^IXIC", AssetClass.INDEX),
    ],
)
def test_infer_asset_class_known_patterns(symbol, expected):
    assert infer_asset_class(symbol) == expected


def test_infer_asset_class_unknown_symbol_defaults_to_stock():
    assert infer_asset_class("SOMEWEIRDTICKER") == AssetClass.STOCK


def test_infer_asset_class_is_case_insensitive_for_suffix_patterns():
    assert infer_asset_class("eurusd=x") == AssetClass.FOREX
    assert infer_asset_class("gc=f") == AssetClass.COMMODITY


def test_infer_asset_class_matches_example_symbols_exactly():
    # Every symbol in the example universe should resolve to the asset class it's listed under.
    from app.config import EXAMPLE_SYMBOLS

    for asset_class, entries in EXAMPLE_SYMBOLS.items():
        for entry in entries:
            assert infer_asset_class(entry["symbol"]) == asset_class


def test_default_commission_bps_matches_asset_class_table():
    for symbol, asset_class in [("AAPL", AssetClass.STOCK), ("BTC-USD", AssetClass.CRYPTO), ("EURUSD=X", AssetClass.FOREX)]:
        assert default_commission_bps(symbol) == DEFAULT_COMMISSION_BPS[asset_class]


def test_default_commission_bps_crypto_higher_than_stock_and_forex():
    # Grounded in real fee structures: crypto exchanges charge meaningfully
    # more than zero/low-commission stock and forex brokers.
    assert default_commission_bps("BTC-USD") > default_commission_bps("AAPL")
    assert default_commission_bps("BTC-USD") > default_commission_bps("EURUSD=X")


def test_all_asset_classes_have_a_default_commission():
    for asset_class in AssetClass:
        assert asset_class in DEFAULT_COMMISSION_BPS
        assert DEFAULT_COMMISSION_BPS[asset_class] > 0


def test_international_indexes_excluded_from_default_universe_but_still_classified():
    """Tested in the default universe and REVERTED: the model picked them
    and lost to the US-only universe in 8 of 9 historical windows (see
    scripts/validate_global_universe_result.json). They remain valid
    symbols for explicit --symbols use; they're just not on the default
    menu."""
    from app.config import EXAMPLE_SYMBOLS, AssetClass, infer_asset_class

    index_symbols = {e["symbol"] for e in EXAMPLE_SYMBOLS[AssetClass.INDEX]}
    for symbol in ("^N225", "^FTSE", "^GDAXI", "^HSI"):
        assert symbol not in index_symbols
        assert infer_asset_class(symbol) is AssetClass.INDEX
