"""Command-line interface.

Examples:
    python -m app.cli strategies
    python -m app.cli backtest --symbol AAPL --strategy sma_crossover --period 2y
    python -m app.cli compare --symbol BTC-USD --period 1y
    python -m app.cli recommend --symbol EURUSD=X --period 1y
"""

from __future__ import annotations

import argparse
import json
import sys

from app.backtest.engine import compare_strategies, run_backtest
from app.data.providers import DataUnavailableError, get_ohlcv
from app.recommend.engine import recommend
from app.strategies import STRATEGY_REGISTRY, all_strategies, build_strategy


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def cmd_strategies(_args: argparse.Namespace) -> None:
    _print_json({"strategies": list(STRATEGY_REGISTRY)})


def cmd_backtest(args: argparse.Namespace) -> None:
    df = get_ohlcv(args.symbol, period=args.period, interval=args.interval)
    strategy = build_strategy(args.strategy)
    result = run_backtest(
        df,
        strategy,
        symbol=args.symbol,
        initial_capital=args.capital,
        commission_bps=args.commission_bps,
    )
    _print_json({"symbol": result.symbol, "strategy": result.strategy, "metrics": result.metrics, "trades": result.trades})


def cmd_compare(args: argparse.Namespace) -> None:
    df = get_ohlcv(args.symbol, period=args.period, interval=args.interval)
    results = compare_strategies(
        df, all_strategies(), symbol=args.symbol, initial_capital=args.capital, commission_bps=args.commission_bps
    )
    _print_json(
        {
            "symbol": args.symbol,
            "ranked_by": "avg_profit_per_trade_pct",
            "results": [{"strategy": r.strategy, "metrics": r.metrics} for r in results],
        }
    )


def cmd_recommend(args: argparse.Namespace) -> None:
    df = get_ohlcv(args.symbol, period=args.period, interval=args.interval)
    result = recommend(df, symbol=args.symbol, initial_capital=args.capital, commission_bps=args.commission_bps)
    _print_json(result)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Trading signals CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("strategies", help="Lista las estrategias disponibles").set_defaults(func=cmd_strategies)

    backtest_parser = subparsers.add_parser("backtest", help="Backtest de una estrategia sobre un símbolo")
    backtest_parser.add_argument("--symbol", required=True)
    backtest_parser.add_argument("--strategy", required=True, choices=list(STRATEGY_REGISTRY))
    backtest_parser.add_argument("--period", default="2y")
    backtest_parser.add_argument("--interval", default="1d")
    backtest_parser.add_argument("--capital", type=float, default=10_000.0)
    backtest_parser.add_argument("--commission-bps", type=float, default=5.0)
    backtest_parser.set_defaults(func=cmd_backtest)

    compare_parser = subparsers.add_parser("compare", help="Compara todas las estrategias sobre un símbolo")
    compare_parser.add_argument("--symbol", required=True)
    compare_parser.add_argument("--period", default="2y")
    compare_parser.add_argument("--interval", default="1d")
    compare_parser.add_argument("--capital", type=float, default=10_000.0)
    compare_parser.add_argument("--commission-bps", type=float, default=5.0)
    compare_parser.set_defaults(func=cmd_compare)

    recommend_parser = subparsers.add_parser("recommend", help="Recomendación actual de compra/venta para un símbolo")
    recommend_parser.add_argument("--symbol", required=True)
    recommend_parser.add_argument("--period", default="2y")
    recommend_parser.add_argument("--interval", default="1d")
    recommend_parser.add_argument("--capital", type=float, default=10_000.0)
    recommend_parser.add_argument("--commission-bps", type=float, default=5.0)
    recommend_parser.set_defaults(func=cmd_recommend)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (DataUnavailableError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
