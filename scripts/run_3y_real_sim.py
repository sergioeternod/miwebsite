"""Portfolio simulation over real market data for the last 3 years, with
daily ensemble recalculation (step=1), plus a daily P&L series ready for
charting. Requires the environment's network policy to allow reaching
Yahoo Finance (see app/data/providers.py for the fallback chain used)."""

import json
import time

from app.portfolio import simulate_portfolio_real

START_DATE = "2023-07-30"  # 3 years before "today" (2026-07-30) in this run
PERIOD = "5y"  # ~2y of warmup before START_DATE + the 3y simulated window

if __name__ == "__main__":
    t0 = time.time()
    report = simulate_portfolio_real(
        start_date=START_DATE,
        period=PERIOD,
        portfolio_size=5,
        step=1,
    )
    elapsed = time.time() - t0

    with open("scripts/sim_3y_real_result.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)

    print(f"elapsed_seconds={elapsed:.1f}")
    print(f"start_date={report['start_date']} end_date={report['end_date']} num_trading_days={report['num_trading_days']}")
    print(f"initial_capital={report['initial_capital']} final_equity={report['final_equity']}")
    print(f"total_pnl_amount={report['total_pnl_amount']} total_return_pct={report['total_return_pct']}")
    print("portfolio:", report["portfolio"])
    print("hindsight_summary:", report["hindsight_summary"])
    for p in report["per_symbol"]:
        print(
            f"  {p['symbol']}: final_equity={p['final_equity']} pnl={p['pnl_amount']} "
            f"num_trades={p['metrics']['num_trades']} win_rate={p['metrics']['win_rate_pct']}"
        )
    if report["errors"]:
        print("errors:", report["errors"])
