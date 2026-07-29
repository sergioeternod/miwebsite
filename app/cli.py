"""Command-line interface.

Examples:
    python -m app.cli strategies
    python -m app.cli backtest --symbol AAPL --strategy sma_crossover --period 2y
    python -m app.cli compare --symbol BTC-USD --period 1y
    python -m app.cli recommend --symbol EURUSD=X --period 1y
    python -m app.cli recommend --symbol AAPL --with-earnings
    python -m app.cli earnings --symbol AAPL
    python -m app.cli simulate --synthetic --out /tmp/report.json
    python -m app.cli simulate --symbol AAPL --period 3y --strategy macd_crossover
"""

from __future__ import annotations

import argparse
import json
import sys

from dotenv import load_dotenv

load_dotenv()  # lee .env si existe (API keys como FINNHUB_API_KEY); no sobreescribe variables ya definidas en el entorno

from app.backtest.engine import compare_strategies, run_backtest
from app.data.finnhub_client import FinnhubUnavailableError
from app.data.providers import DataUnavailableError, get_ohlcv
from app.fundamentals.earnings import apply_earnings_overlay, earnings_report
from app.ranking import rank_real_symbols, rank_synthetic_profiles
from app.recommend.engine import recommend
from app.screener import screen_real_symbols, screen_synthetic
from app.simulate import simulate_symbol, simulate_synthetic
from app.strategies import STRATEGY_REGISTRY, all_strategies, build_strategy
from app.validation.report import validate_symbol, validate_synthetic


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def cmd_strategies(_args: argparse.Namespace) -> None:
    _print_json({"strategies": list(STRATEGY_REGISTRY)})


def cmd_backtest(args: argparse.Namespace) -> None:
    df = get_ohlcv(args.symbol, period=args.period, interval=args.interval)
    strategy = build_strategy(args.strategy, allow_short=not args.no_short)
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
        df,
        all_strategies(allow_short=not args.no_short),
        symbol=args.symbol,
        initial_capital=args.capital,
        commission_bps=args.commission_bps,
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
    result = recommend(
        df,
        symbol=args.symbol,
        initial_capital=args.capital,
        commission_bps=args.commission_bps,
        allow_short=not args.no_short,
    )
    if args.with_earnings:
        result = apply_earnings_overlay(result, args.symbol, api_key=args.finnhub_key)
    _print_json(result)


def cmd_earnings(args: argparse.Namespace) -> None:
    report = earnings_report(args.symbol, api_key=args.finnhub_key)
    _print_json(report)


def cmd_simulate(args: argparse.Namespace) -> None:
    if args.synthetic:
        report = simulate_synthetic(
            strategy_name=args.strategy,
            symbol=args.symbol or "SYNTH",
            seed=args.seed,
            start_date=args.start_date,
            end_date=args.end_date,
            initial_capital=args.capital,
            commission_bps=args.commission_bps,
            allow_short=not args.no_short,
        )
    else:
        if not args.symbol:
            raise ValueError("--symbol es obligatorio salvo que uses --synthetic")
        report = simulate_symbol(
            args.symbol,
            strategy_name=args.strategy,
            period=args.period,
            interval=args.interval,
            start_date=args.start_date,
            end_date=args.end_date,
            initial_capital=args.capital,
            commission_bps=args.commission_bps,
            allow_short=not args.no_short,
        )

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)

    summary = {
        "symbol": report["symbol"],
        "period": f"{report['period_start']} -> {report['period_end']}",
        "num_bars": report["num_bars"],
        "results": [
            {"strategy": r["strategy"], "final_equity": r["final_equity"], "metrics": r["metrics"]}
            for r in report["results"]
        ],
    }
    if args.out:
        summary["full_report_saved_to"] = args.out
    _print_json(summary)


def cmd_validate(args: argparse.Namespace) -> None:
    kwargs = dict(
        split_ratio=args.split_ratio,
        horizon=args.horizon,
        step=args.step,
        warmup=args.warmup,
        initial_capital=args.capital,
        commission_bps=args.commission_bps,
        allow_short=not args.no_short,
    )
    if args.synthetic:
        report = validate_synthetic(
            symbol=args.symbol or "SYNTH",
            seed=args.seed,
            start_date=args.start_date,
            end_date=args.end_date,
            **kwargs,
        )
    else:
        if not args.symbol:
            raise ValueError("--symbol es obligatorio salvo que uses --synthetic")
        report = validate_symbol(
            args.symbol,
            period=args.period,
            interval=args.interval,
            start_date=args.start_date,
            end_date=args.end_date,
            **kwargs,
        )

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)

    summary = {
        "symbol": report["symbol"],
        "period": f"{report['period_start']} -> {report['period_end']}",
        "num_bars": report["num_bars"],
        "out_of_sample": [
            {
                "strategy": r["strategy"],
                "split_date": r["split_date"],
                "expectativa_avg_profit_per_trade_pct": r["period_a"]["metrics"]["avg_profit_per_trade_pct"],
                "realidad_avg_profit_per_trade_pct": r["period_b"]["metrics"]["avg_profit_per_trade_pct"],
                "profitability_sign_matches": r["consistency"]["profitability_sign_matches"],
            }
            for r in report["out_of_sample"]
        ],
        "directional_accuracy": [{"strategy": r["strategy"], **r["accuracy"]} for r in report["directional_accuracy"]],
        "recommendation_walk_forward_summary": report["recommendation_walk_forward"]["summary"],
    }
    if args.out:
        summary["full_report_saved_to"] = args.out
    _print_json(summary)


def cmd_rank(args: argparse.Namespace) -> None:
    if args.synthetic:
        report = rank_synthetic_profiles(
            seed=args.seed,
            allow_short=not args.no_short,
            initial_capital=args.capital,
            commission_bps=args.commission_bps,
        )
    else:
        if not args.symbols:
            raise ValueError("--symbols es obligatorio salvo que uses --synthetic")
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
        report = rank_real_symbols(
            symbols,
            period=args.period,
            interval=args.interval,
            start_date=args.start_date,
            end_date=args.end_date,
            allow_short=not args.no_short,
            initial_capital=args.capital,
            commission_bps=args.commission_bps,
        )

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)

    summary = {
        "symbols": report["symbols"],
        "strategies": report["strategies"],
        "best_symbol_per_strategy": report["best_symbol_per_strategy"],
        "best_strategy_per_symbol": report["best_strategy_per_symbol"],
    }
    if args.out:
        summary["full_report_saved_to"] = args.out
    _print_json(summary)


def cmd_screen(args: argparse.Namespace) -> None:
    if args.synthetic:
        report = screen_synthetic(seed=args.seed, top_n=args.top_n)
    else:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()] if args.symbols else None
        report = screen_real_symbols(symbols, period=args.period, interval=args.interval, top_n=args.top_n)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)

    summary = {"top_by_window": report["top_by_window"], "errors": report["errors"]}
    if args.out:
        summary["full_report_saved_to"] = args.out
    _print_json(summary)


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
    backtest_parser.add_argument("--no-short", action="store_true", help="Desactiva las posiciones en corto")
    backtest_parser.set_defaults(func=cmd_backtest)

    compare_parser = subparsers.add_parser("compare", help="Compara todas las estrategias sobre un símbolo")
    compare_parser.add_argument("--symbol", required=True)
    compare_parser.add_argument("--period", default="2y")
    compare_parser.add_argument("--interval", default="1d")
    compare_parser.add_argument("--capital", type=float, default=10_000.0)
    compare_parser.add_argument("--commission-bps", type=float, default=5.0)
    compare_parser.add_argument("--no-short", action="store_true", help="Desactiva las posiciones en corto")
    compare_parser.set_defaults(func=cmd_compare)

    recommend_parser = subparsers.add_parser("recommend", help="Recomendación actual de compra/venta para un símbolo")
    recommend_parser.add_argument("--symbol", required=True)
    recommend_parser.add_argument("--period", default="2y")
    recommend_parser.add_argument("--interval", default="1d")
    recommend_parser.add_argument("--capital", type=float, default=10_000.0)
    recommend_parser.add_argument("--commission-bps", type=float, default=5.0)
    recommend_parser.add_argument("--no-short", action="store_true", help="Desactiva las posiciones en corto")
    recommend_parser.add_argument(
        "--with-earnings", action="store_true", help="Ajusta la confianza con el historial de sorpresas de earnings (Finnhub)"
    )
    recommend_parser.add_argument(
        "--finnhub-key", default=None, help="API key de Finnhub (si se omite, usa la variable de entorno FINNHUB_API_KEY)"
    )
    recommend_parser.set_defaults(func=cmd_recommend)

    earnings_parser = subparsers.add_parser(
        "earnings", help="Historial de sorpresas de EPS (real vs. estimado) y próxima fecha de reporte (Finnhub)"
    )
    earnings_parser.add_argument("--symbol", required=True)
    earnings_parser.add_argument(
        "--finnhub-key", default=None, help="API key de Finnhub (si se omite, usa la variable de entorno FINNHUB_API_KEY)"
    )
    earnings_parser.set_defaults(func=cmd_earnings)

    simulate_parser = subparsers.add_parser(
        "simulate", help="Simula una estrategia (o todas) sobre datos históricos reales o sintéticos"
    )
    simulate_parser.add_argument("--symbol", default=None, help="Símbolo real (omite si usas --synthetic)")
    simulate_parser.add_argument(
        "--strategy", default=None, choices=list(STRATEGY_REGISTRY), help="Si se omite, corre y rankea todas"
    )
    simulate_parser.add_argument("--synthetic", action="store_true", help="Usa un escenario histórico sintético")
    simulate_parser.add_argument("--seed", type=int, default=42, help="Semilla del escenario sintético")
    simulate_parser.add_argument("--period", default="2y")
    simulate_parser.add_argument("--interval", default="1d")
    simulate_parser.add_argument("--start-date", default=None, help="ISO, ej. 2023-06-01 (prioridad sobre --period)")
    simulate_parser.add_argument("--end-date", default=None, help="ISO, ej. 2023-09-30")
    simulate_parser.add_argument("--capital", type=float, default=10_000.0)
    simulate_parser.add_argument("--commission-bps", type=float, default=5.0)
    simulate_parser.add_argument("--no-short", action="store_true", help="Desactiva las posiciones en corto")
    simulate_parser.add_argument("--out", default=None, help="Ruta donde guardar el reporte completo en JSON")
    simulate_parser.set_defaults(func=cmd_simulate)

    validate_parser = subparsers.add_parser(
        "validate",
        help="Compara expectativa vs realidad: fuera de muestra, precisión direccional y precisión de recomendaciones",
    )
    validate_parser.add_argument("--symbol", default=None, help="Símbolo real (omite si usas --synthetic)")
    validate_parser.add_argument("--synthetic", action="store_true", help="Usa un escenario histórico sintético")
    validate_parser.add_argument("--seed", type=int, default=42, help="Semilla del escenario sintético")
    validate_parser.add_argument("--period", default="2y")
    validate_parser.add_argument("--interval", default="1d")
    validate_parser.add_argument("--start-date", default=None, help="ISO, ej. 2023-06-01 (prioridad sobre --period)")
    validate_parser.add_argument("--end-date", default=None, help="ISO, ej. 2023-09-30")
    validate_parser.add_argument(
        "--split-ratio", type=float, default=0.5, help="Fracción del histórico usada como periodo 'expectativa'"
    )
    validate_parser.add_argument(
        "--horizon", type=int, default=10, help="Barras hacia adelante para medir el retorno real de cada recomendación"
    )
    validate_parser.add_argument("--step", type=int, default=10, help="Separación en barras entre evaluaciones")
    validate_parser.add_argument("--warmup", type=int, default=110, help="Barras iniciales antes de empezar a evaluar")
    validate_parser.add_argument("--capital", type=float, default=10_000.0)
    validate_parser.add_argument("--commission-bps", type=float, default=5.0)
    validate_parser.add_argument("--no-short", action="store_true", help="Desactiva las posiciones en corto")
    validate_parser.add_argument("--out", default=None, help="Ruta donde guardar el reporte completo en JSON")
    validate_parser.set_defaults(func=cmd_validate)

    rank_parser = subparsers.add_parser(
        "rank", help="Compara todas las estrategias sobre varios símbolos: ¿cuál funciona mejor con cuál?"
    )
    rank_parser.add_argument("--symbols", default=None, help="Lista separada por comas, ej. AAPL,MSFT,BTC-USD")
    rank_parser.add_argument("--synthetic", action="store_true", help="Usa perfiles de mercado sintéticos (sin red)")
    rank_parser.add_argument("--seed", type=int, default=42, help="Semilla de los perfiles sintéticos")
    rank_parser.add_argument("--period", default="2y")
    rank_parser.add_argument("--interval", default="1d")
    rank_parser.add_argument("--start-date", default=None, help="ISO, ej. 2023-06-01 (prioridad sobre --period)")
    rank_parser.add_argument("--end-date", default=None, help="ISO, ej. 2023-09-30")
    rank_parser.add_argument("--capital", type=float, default=10_000.0)
    rank_parser.add_argument("--commission-bps", type=float, default=5.0)
    rank_parser.add_argument("--no-short", action="store_true", help="Desactiva las posiciones en corto")
    rank_parser.add_argument("--out", default=None, help="Ruta donde guardar el reporte completo en JSON")
    rank_parser.set_defaults(func=cmd_rank)

    screen_parser = subparsers.add_parser(
        "screen", help="Sugiere los símbolos más rentables por retorno en semana/mes/año"
    )
    screen_parser.add_argument(
        "--symbols", default=None, help="Lista separada por comas; si se omite usa el universo de ejemplo"
    )
    screen_parser.add_argument("--synthetic", action="store_true", help="Usa perfiles de mercado sintéticos (sin red)")
    screen_parser.add_argument("--seed", type=int, default=42, help="Semilla de los perfiles sintéticos")
    screen_parser.add_argument("--period", default="2y")
    screen_parser.add_argument("--interval", default="1d")
    screen_parser.add_argument("--top-n", type=int, default=5, help="Cuántos símbolos mostrar por ventana")
    screen_parser.add_argument("--out", default=None, help="Ruta donde guardar el reporte completo en JSON")
    screen_parser.set_defaults(func=cmd_screen)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (DataUnavailableError, FinnhubUnavailableError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
