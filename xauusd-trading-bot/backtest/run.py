"""CLI: python -m backtest.run data.csv [--risk 0.5 --rr 2 ...] [--trades out.csv]
       python -m backtest.run --synthetic          (smoke test on generated data)"""
from __future__ import annotations

import argparse
import json
from dataclasses import fields

from .engine import Params, load_csv, run
from .sample_data import synthetic_xauusd


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("csv", nargs="?", help="OHLC CSV (TradingView export works)")
    ap.add_argument("--synthetic", action="store_true", help="use synthetic data instead of a CSV")
    ap.add_argument("--trades", help="write trade list to this CSV")
    for f in fields(Params):
        flag = "--" + f.name.replace("_", "-")
        if f.type in ("bool", bool):
            ap.add_argument(flag, type=lambda s: s.lower() in ("1", "true", "yes"), default=None)
        else:
            ap.add_argument(flag, type=type(f.default), default=None)
    args = ap.parse_args(argv)

    if args.synthetic:
        df = synthetic_xauusd(bars=4000, freq="1D")
        print("WARNING: synthetic data, results say nothing about real gold markets\n")
    elif args.csv:
        df = load_csv(args.csv)
    else:
        ap.error("give a CSV path or --synthetic")

    overrides = {f.name: getattr(args, f.name) for f in fields(Params) if getattr(args, f.name) is not None}
    res = run(df, Params(**overrides))
    print(json.dumps(res.stats, indent=2))
    if args.trades:
        res.trades_frame().to_csv(args.trades, index=False)
        print(f"trades written to {args.trades}")


if __name__ == "__main__":
    main()
