import re
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
        # Mercados internacionales. Nota honesta: cotizan en su moneda local
        # (yen, libra, euro, dólar de Hong Kong) y el simulador mide el
        # rendimiento del índice en esa moneda, sin conversión cambiaria —
        # en la práctica se compran vía ETFs en dólares (EWJ, EWU, EWG,
        # FXI/MCHI), cuyo retorno difiere por el tipo de cambio. Para China
        # se usa el Hang Seng, el proxy líquido e invertible desde fuera.
        {"symbol": "^N225", "name": "Nikkei 225 (Japón)"},
        {"symbol": "^FTSE", "name": "FTSE 100 (Reino Unido)"},
        {"symbol": "^GDAXI", "name": "DAX (Alemania)"},
        {"symbol": "^HSI", "name": "Hang Seng (China/Hong Kong)"},
    ],
}

DEFAULT_INTERVAL = "1d"
DEFAULT_PERIOD = "2y"

# Rough "all-in" round-trip trading cost (commission + typical spread/slippage
# for a liquid instrument) at major retail platforms, expressed one-way in
# basis points — this is what a single entry or exit costs, matching how
# commission_bps is applied per position change throughout this app. Grounded
# in real fee structures rather than one flat guess for every instrument:
# - Stocks/index ETFs: most major US brokers (Schwab, Fidelity, Robinhood,
#   E*TRADE) charge $0 commission, but liquid-stock spread/slippage still
#   costs a couple of bps; IBKR-style per-share pricing lands in the same
#   range. ~2 bps.
# - Forex: ECN/raw-spread brokers (Interactive Brokers, Pepperstone) run
#   ~0.4-0.8 pips all-in round-turn on EUR/USD (~0.2-0.4 bps one-way);
#   "commission-free" retail brokers (eToro, Plus500) embed a wider spread
#   instead, so a blended average across major platforms lands higher. ~1.5 bps.
# - Commodities (futures): per-contract fees (e.g. ~$2-5/contract at
#   NinjaTrader/AMP) translate to roughly this share of notional for a
#   liquid contract. ~3 bps.
# - Crypto: centralized exchanges range widely — Binance/Kraken run
#   ~10-25 bps taker, Coinbase's retail maker/taker (0.4%/0.6%) is much
#   higher — a blended average across major platforms is well above the
#   near-zero cost of stocks/forex. ~25 bps.
DEFAULT_COMMISSION_BPS = {
    AssetClass.STOCK: 2.0,
    AssetClass.INDEX: 2.0,
    AssetClass.COMMODITY: 3.0,
    AssetClass.FOREX: 1.5,
    AssetClass.CRYPTO: 25.0,
}

_SYMBOL_ASSET_CLASS = {
    entry["symbol"]: asset_class for asset_class, entries in EXAMPLE_SYMBOLS.items() for entry in entries
}
_CRYPTO_PAIR_RE = re.compile(r"^[A-Z0-9]+-(USD|USDT|USDC|EUR|GBP|BTC|ETH)$")


def infer_asset_class(symbol: str) -> AssetClass:
    """Best-effort guess at a symbol's asset class from its Yahoo-Finance-style
    ticker convention, falling back to the example-symbol list for anything
    that matches it exactly. Defaults to STOCK when nothing else matches —
    the most common case and the least aggressive default commission."""
    if symbol in _SYMBOL_ASSET_CLASS:
        return _SYMBOL_ASSET_CLASS[symbol]
    upper = symbol.upper()
    if upper.endswith("=X"):
        return AssetClass.FOREX
    if upper.endswith("=F"):
        return AssetClass.COMMODITY
    if upper.startswith("^"):
        return AssetClass.INDEX
    if _CRYPTO_PAIR_RE.match(upper):
        return AssetClass.CRYPTO
    return AssetClass.STOCK


def default_commission_bps(symbol: str) -> float:
    """The realistic one-way commission/cost assumption for `symbol`, used
    whenever a caller doesn't explicitly specify one (see DEFAULT_COMMISSION_BPS)."""
    return DEFAULT_COMMISSION_BPS[infer_asset_class(symbol)]
