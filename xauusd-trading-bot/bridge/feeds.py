"""Live market data for the 24/7 scanner: completed daily bars and the latest price.

  CoinbaseFeed : crypto (public API, no key). Daily bars close at 00:00 UTC.
  OandaFeed    : gold and forex from your OANDA account (practice or live). Daily bars close at 17:00 New York.
  YahooFeed    : gold and forex from Yahoo Finance's unofficial API. Paper trading only (no SLA, delayed,
                 malformed forex closes are repaired the same way as for the backtests).

Every feed returns only COMPLETED daily bars (UTC DatetimeIndex, columns open/high/low/close), so the scanner
never acts on a half-finished day.
"""
from __future__ import annotations

import time as _time
from datetime import datetime, timedelta, timezone
from typing import Optional, Protocol

import pandas as pd

from backtest.markets import COINBASE, CRYPTO, FX, OANDA, YAHOO

UA = {"User-Agent": "xauusd-bridge/1.0"}


class Feed(Protocol):
    def daily_bars(self, symbol: str) -> pd.DataFrame: ...
    def last_price(self, symbol: str) -> float: ...


def _frame(rows: list[tuple]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close"]).astype(
        {"open": float, "high": float, "low": float, "close": float})
    df.index = pd.DatetimeIndex(pd.to_datetime(df.pop("time"), utc=True), name="time")
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df[(df.high >= df.low) & (df.open > 0)]


class CoinbaseFeed:
    BASE = "https://api.exchange.coinbase.com"

    def __init__(self, session=None, timeout: float = 15.0, days: int = 900,
                 clock=lambda: datetime.now(timezone.utc)):
        import requests
        self.http = session or requests.Session()
        self.http.headers.update(UA)
        self.timeout = timeout
        self.days = days
        self.clock = clock

    def daily_bars(self, symbol: str) -> pd.DataFrame:
        product = COINBASE[symbol]
        today = self.clock().replace(hour=0, minute=0, second=0, microsecond=0)
        rows: list[tuple] = []
        end = today
        remaining = self.days
        while remaining > 0:                       # max 300 candles per request
            n = min(300, remaining)
            start = end - timedelta(days=n)
            r = self.http.get(f"{self.BASE}/products/{product}/candles",
                              params={"granularity": 86400, "start": start.isoformat(), "end": end.isoformat()},
                              timeout=self.timeout)
            r.raise_for_status()
            # [time, low, high, open, close, volume], newest first
            rows += [(datetime.fromtimestamp(c[0], timezone.utc), c[3], c[2], c[1], c[4]) for c in r.json()]
            end, remaining = start, remaining - n
        df = _frame(rows)
        return df[df.index < today]                # drop today's unfinished candle

    def last_price(self, symbol: str) -> float:
        r = self.http.get(f"{self.BASE}/products/{COINBASE[symbol]}/ticker", timeout=self.timeout)
        r.raise_for_status()
        return float(r.json()["price"])


class OandaFeed:
    HOSTS = {"practice": "https://api-fxpractice.oanda.com", "live": "https://api-fxtrade.oanda.com"}

    def __init__(self, token: str, env: str = "practice", session=None, timeout: float = 15.0):
        import requests
        self.http = session or requests.Session()
        self.http.headers.update({**UA, "Authorization": f"Bearer {token}"})
        self.base = self.HOSTS[env]
        self.timeout = timeout

    def _candles(self, symbol: str, **params) -> list[dict]:
        r = self.http.get(f"{self.base}/v3/instruments/{OANDA[symbol]}/candles",
                          params={"price": "M", **params}, timeout=self.timeout)
        r.raise_for_status()
        return r.json()["candles"]

    def daily_bars(self, symbol: str) -> pd.DataFrame:
        cs = self._candles(symbol, granularity="D", count=1000, dailyAlignment=17,
                           alignmentTimezone="America/New_York")
        return _frame([(c["time"], c["mid"]["o"], c["mid"]["h"], c["mid"]["l"], c["mid"]["c"])
                       for c in cs if c.get("complete")])

    def last_price(self, symbol: str) -> float:
        cs = self._candles(symbol, granularity="M1", count=1)
        return float(cs[-1]["mid"]["c"])


class YahooFeed:
    URL = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"

    def __init__(self, session=None, timeout: float = 15.0, clock=lambda: datetime.now(timezone.utc)):
        import requests
        self.http = session or requests.Session()
        self.http.headers.update({"User-Agent": "Mozilla/5.0"})
        self.timeout = timeout
        self.clock = clock

    def _chart(self, symbol: str, rng: str) -> dict:
        r = self.http.get(self.URL.format(sym=YAHOO[symbol]), params={"interval": "1d", "range": rng},
                          timeout=self.timeout)
        r.raise_for_status()
        return r.json()["chart"]["result"][0]

    def daily_bars(self, symbol: str) -> pd.DataFrame:
        from backtest.download import repair_fx_closes
        res = self._chart(symbol, "5y")
        q = res["indicators"]["quote"][0]
        raw = pd.DataFrame({"time": res["timestamp"], "open": q["open"], "high": q["high"],
                            "low": q["low"], "close": q["close"]}).dropna()
        if symbol in FX:
            raw = repair_fx_closes(raw)            # also drops the last bar (no true close yet)
        df = _frame([(datetime.fromtimestamp(t, timezone.utc), o, h, low, c)
                     for t, o, h, low, c in raw[["time", "open", "high", "low", "close"]].itertuples(index=False)])
        today = self.clock().replace(hour=0, minute=0, second=0, microsecond=0)
        return df[df.index < today]                # the current session's bar is not finished

    def last_price(self, symbol: str) -> float:
        return float(self._chart(symbol, "1d")["meta"]["regularMarketPrice"])


class CachedFeed:
    """Wraps a feed: daily bars are refetched at most every `ttl_s` seconds (they change once a day)."""

    def __init__(self, feed: Feed, ttl_s: float = 900.0, now=_time.monotonic):
        self.feed = feed
        self.ttl_s = ttl_s
        self.now = now
        self._cache: dict[str, tuple[float, pd.DataFrame]] = {}

    def daily_bars(self, symbol: str) -> pd.DataFrame:
        hit = self._cache.get(symbol)
        if hit and self.now() - hit[0] < self.ttl_s:
            return hit[1]
        df = self.feed.daily_bars(symbol)
        self._cache[symbol] = (self.now(), df)
        return df

    def last_price(self, symbol: str) -> float:
        return self.feed.last_price(symbol)


def make_feeds(cfg) -> dict[str, Feed]:
    """symbol -> feed for every allowed symbol."""
    nonfx: Optional[Feed] = None
    choice = cfg.nonfx_feed
    if choice == "auto":
        choice = "oanda" if (cfg.oanda_token and cfg.broker == "oanda") else "yahoo"
    feeds: dict[str, Feed] = {}
    crypto = CachedFeed(CoinbaseFeed())
    for s in cfg.allowed_symbols:
        if s in CRYPTO:
            feeds[s] = crypto
        else:
            if nonfx is None:
                nonfx = CachedFeed(OandaFeed(cfg.oanda_token, cfg.oanda_env) if choice == "oanda" else YahooFeed())
            feeds[s] = nonfx
    return feeds
