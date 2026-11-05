"""The daily rules, evaluated on live completed bars. Mirrors backtest/portfolio.py exactly:

  entry (breakout, default): close above the highest high of the previous `breakout_len` bars, or above a
                             resistance touched by >= 2 swing highs; confirmed by MACD above its signal line
  entry (trend)            : EMA(fast) > EMA(slow) and close > EMA(fast)
                             (mirror for shorts where allowed; no new entry before USD news for gold/forex)
  stop  : signal close -/+ init_atr x ATR, then trailed at (extreme since the fill bar) -/+ trail_atr x ATR
  exit  : the stop is hit; in trend mode also when the EMA filter flips at a daily close
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from backtest import indicators as ind
from backtest.markets import MarketSpec
from backtest.patterns import resistance_breaks


@dataclass
class Rules:
    entry_mode: str = "breakout"       # breakout | trend
    breakout_len: int = 20
    resistance_entries: bool = True    # also enter on a break of a resistance touched by >= 2 swing highs
    res_pivot: int = 3
    res_tol_atr: float = 0.5
    res_lookback: int = 150
    macd_filter: bool = True           # new entries need MACD(12/26/9) on the trade's side of its signal line
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    fast_len: int = 20
    slow_len: int = 200
    atr_len: int = 14
    init_atr: float = 2.0
    trail_atr: float = 2.5


@dataclass
class PositionState:
    symbol: str
    side: int
    signal_day: str            # ISO date of the bar whose close triggered the entry
    initial_stop: float
    last_stop: float


@dataclass
class Decision:
    action: str                # none | buy | sell | close | update_stop
    ref_price: float = 0.0
    sl_dist: float = 0.0
    stop: float = 0.0
    reason: str = ""


def indicators(bars: pd.DataFrame, r: Rules) -> pd.DataFrame:
    d = bars.copy()
    d["ema_f"] = ind.ema(d.close, r.fast_len)
    d["ema_s"] = ind.ema(d.close, r.slow_len)
    d["atr"] = ind.atr(d, r.atr_len)
    m = ind.ema(d.close, r.macd_fast) - ind.ema(d.close, r.macd_slow)
    d["macd"], d["macd_sig"] = m, ind.ema(m, r.macd_signal)
    return d


def _day(ts) -> date:
    ts = pd.Timestamp(ts)
    return (ts.tz_convert(None) if ts.tzinfo is not None else ts).date()


def trailing_stop(d: pd.DataFrame, st: PositionState, r: Rules) -> float:
    """Recompute the chandelier stop from the entry: deterministic, so restarts can't lose it."""
    stop, ext = st.initial_stop, np.nan
    sig_day = date.fromisoformat(st.signal_day)
    after = d[[_day(t) > sig_day for t in d.index]]
    for _, row in after.iterrows():
        if st.side > 0:
            ext = row.high if np.isnan(ext) else max(ext, row.high)
            stop = max(stop, ext - r.trail_atr * row.atr)
        else:
            ext = row.low if np.isnan(ext) else min(ext, row.low)
            stop = min(stop, ext + r.trail_atr * row.atr)
    return float(stop)


def decide(bars: pd.DataFrame, spec: MarketSpec, r: Rules, state: Optional[PositionState],
           news_next: bool = False) -> Decision:
    """Decision at the close of the last completed bar."""
    if len(bars) < max(r.slow_len, r.atr_len) + 1:
        return Decision("none", reason=f"need {r.slow_len + 1} bars, have {len(bars)}")
    d = indicators(bars, r)
    last = d.iloc[-1]
    up, dn = last.ema_f > last.ema_s, last.ema_f < last.ema_s
    breakout = r.entry_mode == "breakout"
    if state is not None:
        if not breakout and ((state.side > 0 and dn) or (state.side < 0 and up)):
            return Decision("close", ref_price=float(last.close), reason="trend")
        stop = trailing_stop(d, state, r)
        if (state.side > 0 and stop > state.last_stop + 1e-12) or (state.side < 0 and stop < state.last_stop - 1e-12):
            return Decision("update_stop", ref_price=float(last.close), stop=stop, reason="trailing")
        return Decision("none", reason="holding")
    if not last.atr > 0:
        return Decision("none", reason="no ATR")
    if breakout:
        prior = d.iloc[-1 - r.breakout_len:-1]
        long_sig = bool(last.close > prior.high.max())
        if r.resistance_entries and not long_sig:
            long_sig = bool(resistance_breaks(d, d["atr"], r.res_pivot, r.res_tol_atr, r.res_lookback).iloc[-1])
        short_sig = bool(spec.allow_shorts and last.close < prior.low.min())
    else:
        long_sig = bool(up and last.close > last.ema_f)
        short_sig = bool(spec.allow_shorts and dn and last.close < last.ema_f)
    if r.macd_filter:
        long_sig = long_sig and bool(last.macd > last.macd_sig)
        short_sig = short_sig and bool(last.macd < last.macd_sig)
    if not (long_sig or short_sig):
        return Decision("none", reason="no signal")
    if news_next and spec.usd_news:
        return Decision("none", reason="high-impact USD news next session")
    sd = float(r.init_atr * last.atr)
    return Decision("buy" if long_sig else "sell", ref_price=float(last.close), sl_dist=sd,
                    reason=f"{r.entry_mode} entry")
