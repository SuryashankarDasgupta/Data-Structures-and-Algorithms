"""Download daily OHLC history from Yahoo Finance for backtesting (research use only).

    python -m backtest.download --out prices                 # default universe (XAUUSD, BTCUSD, ETHUSD)
    python -m backtest.download --out prices --all           # + 12 forex pairs and 8 cryptocurrencies

Yahoo's forex bars are malformed: the reported close is a snapshot taken right after the open, and the day's
real move shows up as the gap to the next bar's open. repair_fx_closes() replaces each close with the next
bar's open (the end-of-day price) and widens high/low to include it. The last forex bar is dropped (no true
close yet). Validate results on your broker's own data before trading live.
"""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request

import numpy as np
import pandas as pd

from .markets import ALL_MARKETS, DEFAULT_UNIVERSE, FX, YAHOO

URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1d&period1=946684800&period2={now}"


def fetch_yahoo(symbol: str, timeout: float = 30.0) -> pd.DataFrame:
    url = URL.format(sym=YAHOO[symbol], now=int(time.time()))
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        r = json.load(resp)["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    df = pd.DataFrame({"time": r["timestamp"], "open": q["open"], "high": q["high"],
                       "low": q["low"], "close": q["close"]}).dropna()
    return df[(df.high >= df.low) & (df.open > 0)].reset_index(drop=True)


def repair_fx_closes(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["close"] = d["open"].shift(-1).fillna(d["close"])
    d["high"] = np.maximum(d["high"], d["close"])
    d["low"] = np.minimum(d["low"], d["close"])
    return d.iloc[:-1].reset_index(drop=True)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="prices")
    ap.add_argument("--all", action="store_true", help="download every supported market")
    ap.add_argument("symbols", nargs="*")
    args = ap.parse_args(argv)
    syms = [s.upper() for s in args.symbols] or (sorted(ALL_MARKETS) if args.all else list(DEFAULT_UNIVERSE))
    os.makedirs(args.out, exist_ok=True)
    for s in syms:
        try:
            df = fetch_yahoo(s)
            if s in FX:
                df = repair_fx_closes(df)
            df.to_csv(os.path.join(args.out, f"{s}.csv"), index=False)
            first = pd.to_datetime(df.time.iloc[0], unit="s").date()
            last = pd.to_datetime(df.time.iloc[-1], unit="s").date()
            print(f"{s:8} {len(df):6} bars {first} -> {last}")
        except Exception as exc:  # noqa: BLE001
            print(f"{s:8} FAILED: {exc}")


if __name__ == "__main__":
    main()
