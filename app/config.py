from enum import Enum


class AssetClass(str, Enum):
    STOCK = "stock"
    CRYPTO = "crypto"
    FOREX = "forex"
    COMMODITY = "commodity"
    INDEX = "index"


# A few example tickers per asset class, using Yahoo Finance's symbol conventions.
# Users can pass any valid Yahoo Finance symbol directly.
EXAMPLE_SYMBOLS = {
    AssetClass.STOCK: ["AAPL", "MSFT", "TSLA"],
    AssetClass.CRYPTO: ["BTC-USD", "ETH-USD", "SOL-USD"],
    AssetClass.FOREX: ["EURUSD=X", "USDJPY=X", "GBPUSD=X"],
    AssetClass.COMMODITY: ["GC=F", "CL=F", "SI=F"],
    AssetClass.INDEX: ["^GSPC", "^IXIC", "^DJI"],
}

DEFAULT_INTERVAL = "1d"
DEFAULT_PERIOD = "2y"
