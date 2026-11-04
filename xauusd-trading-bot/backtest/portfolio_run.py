"""CLI for the multi-market portfolio backtest.

    python -m backtest.portfolio_run prices                          # default universe, 20 years
    python -m backtest.portfolio_run prices --symbols XAUUSD BTCUSD ETHUSD EURUSD --risk-pct 2
    python -m backtest.portfolio_run prices --fresh-start 2006-11-04 --periods --trades trades.csv
"""
from __future__ import annotations

import argparse
import json
from dataclasses import fields

from .engine import period_stats
from .markets import DEFAULT_UNIVERSE, default_spec
from .portfolio import PortfolioParams, load_markets, portfolio_stats, run_portfolio


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", help="folder of <SYMBOL>.csv files (see python -m backtest.download)")
    ap.add_argument("--symbols", nargs="*", default=list(DEFAULT_UNIVERSE))
    ap.add_argument("--fresh-start", default="2006-11-04", help="open a new account on this date")
    ap.add_argument("--fx-shorts", type=lambda s: s.lower() in ("1", "true", "yes"), default=True)
    ap.add_argument("--crypto-shorts", type=lambda s: s.lower() in ("1", "true", "yes"), default=False)
    ap.add_argument("--periods", action="store_true", help="daily/weekly/monthly/yearly profitability")
    ap.add_argument("--trades", help="write trades to this CSV")
    for f in fields(PortfolioParams):
        ap.add_argument("--" + f.name.replace("_", "-"), type=type(f.default), default=None)
    args = ap.parse_args(argv)
    syms = [s.upper() for s in args.symbols]
    markets = load_markets(args.folder, syms)
    missing = sorted(set(syms) - set(markets))
    if missing:
        ap.error(f"no CSV for {', '.join(missing)} in {args.folder}")
    params = PortfolioParams(**{f.name: getattr(args, f.name) for f in fields(PortfolioParams)
                                if getattr(args, f.name) is not None})
    specs = {s: default_spec(s, args.fx_shorts, args.crypto_shorts) for s in syms}
    res = run_portfolio(markets, params, specs, trade_from=args.fresh_start)
    print(json.dumps(portfolio_stats(res), indent=2))
    if args.periods:
        print()
        print(period_stats(res.equity).to_string())
    if args.trades:
        res.trades_frame().to_csv(args.trades, index=False)
        print(f"trades written to {args.trades}")


if __name__ == "__main__":
    main()
