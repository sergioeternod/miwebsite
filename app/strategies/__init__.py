from app.strategies.base import Strategy
from app.strategies.bollinger_breakout import BollingerBreakoutStrategy
from app.strategies.macd_crossover import MacdCrossoverStrategy
from app.strategies.rsi_reversion import RsiMeanReversionStrategy
from app.strategies.sma_crossover import SmaCrossoverStrategy

STRATEGY_REGISTRY: dict[str, type[Strategy]] = {
    "sma_crossover": SmaCrossoverStrategy,
    "macd_crossover": MacdCrossoverStrategy,
    "rsi_reversion": RsiMeanReversionStrategy,
    "bollinger_breakout": BollingerBreakoutStrategy,
}


def build_strategy(name: str, **params) -> Strategy:
    if name not in STRATEGY_REGISTRY:
        available = ", ".join(STRATEGY_REGISTRY)
        raise ValueError(f"Estrategia desconocida '{name}'. Disponibles: {available}")
    return STRATEGY_REGISTRY[name](**params)


def all_strategies(allow_short: bool = True, **overrides) -> list[Strategy]:
    """Build one instance of every registered strategy. `allow_short` applies
    to all of them unless overridden per-name via `overrides={name: {...}}`."""
    strategies = []
    for name, cls in STRATEGY_REGISTRY.items():
        params = {"allow_short": allow_short, **overrides.get(name, {})}
        strategies.append(cls(**params))
    return strategies
