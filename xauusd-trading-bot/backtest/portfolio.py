"""Multi-market portfolio backtest of the daily trend strategy (forex, metals, crypto).

Every market uses the same rules as pine/xauusd_daily_trend.pine (no per-market tuning):
  entry   : EMA(fast) > EMA(slow) and close > EMA(fast)  (mirror for shorts where allowed) -> next open
  stop    : signal close -/+ init_atr x ATR, trailed at extreme -/+ trail_atr x ATR (never loosens)
  exit    : stop hit, or the trend filter flips (next open)
  news    : optional 'block' of new entries before FOMC/NFP/CPI for markets with a USD leg

Positions are sized in USD notional from portfolio equity, so P&L is computed as
notional x side x (exit / entry - 1). This "percentage return" model works for any quote currency.
Portfolio limits:
  risk_pct            : equity at risk per trade (distance to initial stop)
  max_positions       : open + pending positions
  max_total_risk_pct  : sum of initial risk of all open/pending positions
  max_gross_leverage  : total notional / equity
  max_position_lev    : notional of one position / equity
Costs are a percentage of notional per side (spread + fees). Swaps/funding are NOT modelled.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from . import indicators as ind
from .engine import _stop_fill, event_ahead, load_csv
from .markets import CRYPTO, FX, FX_CROSSES, FX_MAJORS, METALS, MarketSpec, default_spec  # noqa: F401

@dataclass
class PortfolioParams:
    # entry rule: "breakout" (default) = close above the highest high of the previous `breakout_len` bars,
    # exit only by the trailing stop; "trend" = EMA(fast) > EMA(slow) and close > EMA(fast), plus the EMA exit
    entry_mode: str = "breakout"
    breakout_len: int = 20
    fast_len: int = 20
    slow_len: int = 200
    atr_len: int = 14
    init_atr: float = 2.0
    trail_atr: float = 2.5
    # Defaults match the live bridge: RISK_PCT, MAX_POSITIONS, MAX_GROSS_LEVERAGE, MAX_LEVERAGE
    risk_pct: float = 1.0
    max_positions: int = 4
    max_total_risk_pct: float = 100.0   # research knob only (the bridge relies on MAX_POSITIONS x RISK_PCT)
    max_gross_leverage: float = 3.0
    max_position_lev: float = 1.0
    news_mode: str = "block"        # off | block
    initial_capital: float = 25_000.0


@dataclass
class PTrade:
    symbol: str
    side: int
    notional: float
    entry_time: pd.Timestamp
    entry_price: float
    initial_stop: float
    risk_cash: float
    exit_time: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""
    pnl: float = 0.0


@dataclass
class PortfolioResult:
    equity: pd.Series
    trades: list[PTrade]
    params: PortfolioParams
    exposure: pd.DataFrame = field(default_factory=pd.DataFrame)

    def trades_frame(self) -> pd.DataFrame:
        return pd.DataFrame([t.__dict__ for t in self.trades])


def load_markets(folder: str, symbols: Optional[list[str]] = None) -> dict[str, pd.DataFrame]:
    out = {}
    for f in sorted(os.listdir(folder)):
        if not f.endswith(".csv"):
            continue
        sym = f[:-4].upper()
        if symbols and sym not in symbols:
            continue
        out[sym] = load_csv(os.path.join(folder, f))
    return out


def _prepare(df: pd.DataFrame, spec: MarketSpec, p: PortfolioParams, events) -> pd.DataFrame:
    d = df.copy()
    d["ema_f"] = ind.ema(d.close, p.fast_len)
    d["ema_s"] = ind.ema(d.close, p.slow_len)
    d["atr"] = ind.atr(d, p.atr_len)
    if p.entry_mode == "breakout":
        d["long_sig"] = d.close > d.high.rolling(p.breakout_len).max().shift()
        d["short_sig"] = (d.close < d.low.rolling(p.breakout_len).min().shift()) if spec.allow_shorts else False
        d["up"] = False                 # no trend-filter exit: positions leave by the trailing stop only
        d["dn"] = False
    elif p.entry_mode == "trend":
        d["up"] = d.ema_f > d.ema_s
        d["dn"] = d.ema_f < d.ema_s
        d["long_sig"] = d.up & (d.close > d.ema_f)
        d["short_sig"] = (d.dn & (d.close < d.ema_f)) if spec.allow_shorts else False
    else:
        raise ValueError(f"unknown entry_mode {p.entry_mode!r}")
    warm = max(p.slow_len, p.atr_len)
    d.iloc[:warm, d.columns.get_indexer(["long_sig", "short_sig"])] = False
    use_news = p.news_mode == "block" and spec.usd_news and events
    d["news_next"] = event_ahead(d.index, events) if use_news else False
    d["day"] = d.index.tz_convert(None).normalize() if d.index.tz is not None else d.index.normalize()
    return d


def run_portfolio(markets: dict[str, pd.DataFrame], p: Optional[PortfolioParams] = None,
                  specs: Optional[dict[str, MarketSpec]] = None, events=None,
                  start: Optional[str] = None, trade_from: Optional[str] = None) -> PortfolioResult:
    """Simulate the portfolio. `trade_from` blocks entries before that date (indicators still warm up);
    the equity curve is reported from `start` (defaults to trade_from)."""
    p = p or PortfolioParams()
    markets = {s: df for s, df in markets.items() if len(df) > 1}   # markets with no history yet are skipped
    if not markets:
        raise ValueError("no market has data")
    specs = specs or {s: default_spec(s) for s in markets}
    if events is None and p.news_mode != "off":
        from .news import load_events
        events = load_events()
    data = {s: _prepare(df, specs[s], p, events) for s, df in markets.items()}
    days = sorted(set().union(*[set(d["day"]) for d in data.values()]))
    rows = {s: dict(zip(d["day"], range(len(d)))) for s, d in data.items()}
    arr = {s: {c: d[c].to_numpy() for c in ("open", "high", "low", "close", "atr", "up", "dn",
                                             "long_sig", "short_sig", "news_next")} for s, d in data.items()}
    trade_from_ts = pd.Timestamp(trade_from) if trade_from else None

    cash = p.initial_capital
    pos: dict[str, PTrade] = {}
    state: dict[str, dict] = {}          # stop / extreme per open symbol
    pend_entry: dict[str, tuple] = {}    # symbol -> (side, notional, stop, risk_cash)
    pend_close: dict[str, str] = {}
    last_close: dict[str, float] = {}
    trades: list[PTrade] = []
    eq_out, gross_out, npos_out = [], [], []

    def close(sym: str, px: float, when, reason: str) -> None:
        nonlocal cash
        t = pos.pop(sym)
        spec = specs[sym]
        pnl = t.notional * t.side * (px / t.entry_price - 1) - t.notional * spec.cost_pct / 100
        cash += pnl
        t.exit_time, t.exit_price, t.exit_reason = when, px, reason
        t.pnl += pnl
        trades.append(t)
        state.pop(sym, None)

    def mark() -> float:
        return cash + sum(t.notional * t.side * (last_close[s] / t.entry_price - 1) for s, t in pos.items())

    for day in days:
        active = [s for s in data if day in rows[s]]
        # phase 1: fills at the open, then stops
        for s in active:
            i = rows[s][day]
            a = arr[s]
            when = data[s].index[i]
            if s in pend_close and s in pos:
                close(s, a["open"][i], when, pend_close[s])
            pend_close.pop(s, None)
            if s in pend_entry and s not in pos:
                side, notional, stop, risk = pend_entry[s]
                cost = notional * specs[s].cost_pct / 100
                cash -= cost
                pos[s] = PTrade(s, side, notional, when, a["open"][i], stop, risk, pnl=-cost)
                state[s] = {"stop": stop, "ext": np.nan}
            pend_entry.pop(s, None)
            if s in pos:
                px = _stop_fill(pos[s].side, a["open"][i], a["high"][i], a["low"][i], state[s]["stop"])
                if px is not None:
                    reason = "initial_stop" if state[s]["stop"] == pos[s].initial_stop else "trailing_stop"
                    close(s, px, when, reason)
        # phase 2: trail stops, mark closes
        for s in active:
            i = rows[s][day]
            a = arr[s]
            last_close[s] = a["close"][i]
            if s in pos:
                st = state[s]
                if pos[s].side > 0:
                    st["ext"] = a["high"][i] if np.isnan(st["ext"]) else max(st["ext"], a["high"][i])
                    st["stop"] = max(st["stop"], st["ext"] - p.trail_atr * a["atr"][i])
                else:
                    st["ext"] = a["low"][i] if np.isnan(st["ext"]) else min(st["ext"], a["low"][i])
                    st["stop"] = min(st["stop"], st["ext"] + p.trail_atr * a["atr"][i])
        equity = mark()
        # phase 3: exits and entries at the close
        for s in sorted(active):
            i = rows[s][day]
            a = arr[s]
            if s in pos and ((pos[s].side > 0 and a["dn"][i]) or (pos[s].side < 0 and a["up"][i])):
                pend_close[s] = "trend"
        open_risk = sum(t.risk_cash for t in pos.values()) + sum(v[3] for v in pend_entry.values())
        gross = sum(t.notional for t in pos.values()) + sum(v[1] for v in pend_entry.values())
        allowed = trade_from_ts is None or day >= trade_from_ts
        for s in sorted(active):
            if not allowed or s in pos or s in pend_entry:
                continue
            i = rows[s][day]
            a = arr[s]
            if a["news_next"][i] or not (a["long_sig"][i] or a["short_sig"][i]) or not a["atr"][i] > 0:
                continue
            if len(pos) + len(pend_entry) >= p.max_positions:
                break
            side = 1 if a["long_sig"][i] else -1
            sd = p.init_atr * a["atr"][i]
            risk = equity * p.risk_pct / 100
            notional = min(risk / (sd / a["close"][i]), equity * p.max_position_lev)
            notional = min(notional, max(0.0, equity * p.max_gross_leverage - gross))
            risk = notional * sd / a["close"][i]
            if notional <= 0 or open_risk + risk > equity * p.max_total_risk_pct / 100 + 1e-9:
                continue
            pend_entry[s] = (side, notional, a["close"][i] - side * sd, risk)
            open_risk += risk
            gross += notional
        eq_out.append(equity)
        gross_out.append(sum(t.notional for t in pos.values()) / equity if equity > 0 else 0)
        npos_out.append(len(pos))

    for s in list(pos):
        close(s, last_close[s], pd.Timestamp(days[-1]), "end_of_data")
    idx = pd.DatetimeIndex(days, name="day")
    eq = pd.Series(eq_out, index=idx, name="equity")
    if len(eq):
        eq.iloc[-1] = cash
    expo = pd.DataFrame({"gross_leverage": gross_out, "positions": npos_out}, index=idx)
    begin = start or trade_from
    if begin:
        eq = eq.loc[begin:]
        eq = eq / eq.iloc[0] * p.initial_capital
        expo = expo.loc[begin:]
        b = pd.Timestamp(begin)
        trades = [t for t in trades if _naive_day(t.entry_time) >= b]
    return PortfolioResult(eq, trades, p, expo)


def _naive_day(ts: pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(ts)
    return (ts.tz_convert(None) if ts.tzinfo is not None else ts).normalize()


def portfolio_stats(res: PortfolioResult) -> dict:
    eq = res.equity
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    final = float(eq.iloc[-1])
    cagr = (final / float(eq.iloc[0])) ** (1 / years) - 1 if final > 0 else -1.0
    dd = float((eq / eq.cummax() - 1).min())
    r = eq.pct_change().dropna()
    sharpe = float(r.mean() / r.std() * np.sqrt(365)) if r.std() > 0 else 0.0
    pnls = np.array([t.pnl for t in res.trades])
    wins, losses = pnls[pnls > 0], pnls[pnls <= 0]
    by_class: dict[str, float] = {}
    for t in res.trades:
        cls = default_spec(t.symbol).asset_class if t.symbol else "?"
        by_class[cls] = by_class.get(cls, 0.0) + t.pnl
    return {
        "start": str(eq.index[0].date()), "end": str(eq.index[-1].date()),
        "initial_capital": float(eq.iloc[0]), "final_equity": round(final, 2),
        "net_profit": round(final - float(eq.iloc[0]), 2),
        "return_pct": round((final / float(eq.iloc[0]) - 1) * 100, 1),
        "cagr_pct": round(cagr * 100, 2), "max_drawdown_pct": round(dd * 100, 2),
        "return_to_drawdown": round(cagr / abs(dd), 2) if dd < 0 else float("inf"),
        "sharpe": round(sharpe, 2), "trades": int(len(pnls)),
        "win_rate_pct": round(len(wins) / len(pnls) * 100, 1) if len(pnls) else 0.0,
        "profit_factor": round(float(wins.sum() / -losses.sum()), 2) if losses.sum() < 0 else float("inf"),
        "pnl_by_class": {k: round(v, 0) for k, v in sorted(by_class.items())},
        "avg_gross_leverage": round(float(res.exposure["gross_leverage"].mean()), 2) if len(res.exposure) else 0.0,
        "max_gross_leverage": round(float(res.exposure["gross_leverage"].max()), 2) if len(res.exposure) else 0.0,
    }
