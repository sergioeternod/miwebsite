from enum import Enum


class AssetClass(str, Enum):
    STOCK = "stock"
    CRYPTO = "crypto"
    FOREX = "forex"
    COMMODITY = "commodity"
    INDEX = "index"


ASSET_CLASS_LABELS = {
    AssetClass.STOCK: "Acción",
    AssetClass.CRYPTO: "Cripto",
    AssetClass.FOREX: "Divisa",
    AssetClass.COMMODITY: "Commodity",
    AssetClass.INDEX: "Índice",
}

# A few example tickers per asset class, using Yahoo Finance's symbol
# conventions, each with a human-readable name for display. Users can pass
# any valid Yahoo Finance symbol directly — these are just suggestions.
EXAMPLE_SYMBOLS = {
    AssetClass.STOCK: [
        {"symbol": "AAPL", "name": "Apple Inc."},
        {"symbol": "MSFT", "name": "Microsoft Corp."},
        {"symbol": "TSLA", "name": "Tesla Inc."},
        {"symbol": "AMZN", "name": "Amazon.com Inc."},
        {"symbol": "NVDA", "name": "NVIDIA Corp."},
    ],
    AssetClass.CRYPTO: [
        {"symbol": "BTC-USD", "name": "Bitcoin / Dólar"},
        {"symbol": "ETH-USD", "name": "Ethereum / Dólar"},
        {"symbol": "SOL-USD", "name": "Solana / Dólar"},
        {"symbol": "XRP-USD", "name": "XRP / Dólar"},
    ],
    AssetClass.FOREX: [
        {"symbol": "EURUSD=X", "name": "Euro / Dólar"},
        {"symbol": "USDJPY=X", "name": "Dólar / Yen japonés"},
        {"symbol": "GBPUSD=X", "name": "Libra esterlina / Dólar"},
        {"symbol": "USDMXN=X", "name": "Dólar / Peso mexicano"},
    ],
    AssetClass.COMMODITY: [
        {"symbol": "GC=F", "name": "Oro (futuro)"},
        {"symbol": "CL=F", "name": "Petróleo crudo WTI (futuro)"},
        {"symbol": "SI=F", "name": "Plata (futuro)"},
    ],
    AssetClass.INDEX: [
        {"symbol": "^GSPC", "name": "S&P 500"},
        {"symbol": "^IXIC", "name": "Nasdaq Composite"},
        {"symbol": "^DJI", "name": "Dow Jones Industrial Average"},
    ],
}

DEFAULT_INTERVAL = "1d"
DEFAULT_PERIOD = "2y"
