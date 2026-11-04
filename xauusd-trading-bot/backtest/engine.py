"""Bar-by-bar simulation of the XAUUSD Trend Pullback strategy.

Fill model (matches TradingView's default broker emulator closely):
  * signals are evaluated on bar close, market orders fill at the next bar's open
  * stop/target are measured from the fill price; they can trigger on the fill bar
  * if both stop and target lie inside one bar, the intrabar path is assumed to visit the
    extreme closer to the open first (TradingView's rule); gaps through a level fill at the open
  * spread/commission is charged per ounce per side
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from . import indicators as ind


@dataclass
class Params:
    fast_len: int = 21
    slow_len: int = 50
    trend_len: int = 200
    adx_len: int = 14
    adx_min: float = 20.0
    risk_pct: float = 0.5
    atr_len: int = 14
    sl_atr: float = 1.5
    rr: float = 2.0
    max_units: int = 100
    max_day_loss_pct: float = 2.0
    max_day_orders: int = 6
    use_session: bool = True
    session_start_hour: int = 7      # UTC, inclusive
    session_end_hour: int = 20       # UTC, exclusive
    flat_friday: bool = True
    initial_capital: float = 10_000.0
    commission_per_unit: float = 0.15


@dataclass
class Trade:
    side: int
    units: int
    entry_time: pd.Timestamp
    entry_price: float
    stop: float
    target: float
    risk_cash: float
    exit_time: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    exit_reason: str = ""
    pnl: float = 0.0

    @property
    def r_multiple(self) -> float:
        return self.pnl / self.risk_cash if self.risk_cash else 0.0


@dataclass
class Result:
    trades: list[Trade]
    equity: pd.Series
    params: Params
    stats: dict = field(default_factory=dict)

    def trades_frame(self) -> pd.DataFrame:
        rows = [{**asdict(t), "r_multiple": t.r_multiple} for t in self.trades]
        return pd.DataFrame(rows)


def load_csv(path: str) -> pd.DataFrame:
    """Load OHLC data. Accepts TradingView 'Export chart data' CSVs (unix-seconds `time`)
    or any CSV with a datetime column named time/date/datetime/timestamp."""
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    tcol = next((c for c in ("time", "datetime", "date", "timestamp") if c in df.columns), None)
    if tcol is None:
        raise ValueError("CSV needs a time/datetime/date/timestamp column")
    t = df[tcol]
    if np.issubdtype(t.dtype, np.number):
        unit = "ms" if t.iloc[0] > 1e11 else "s"
        idx = pd.to_datetime(t, unit=unit, utc=True)
    else:
        idx = pd.to_datetime(t, utc=True)
    out = df[["open", "high", "low", "close"]].astype(float)
    out.index = pd.DatetimeIndex(idx, name="time")
    return out.sort_index()


def compute_signals(df: pd.DataFrame, p: Params) -> pd.DataFrame:
    d = df.copy()
    d["ema_f"] = ind.ema(d["close"], p.fast_len)
    d["ema_s"] = ind.ema(d["close"], p.slow_len)
    d["ema_t"] = ind.ema(d["close"], p.trend_len)
    d["atr"] = ind.atr(d, p.atr_len)
    d["adx"] = ind.adx(d, p.adx_len, p.adx_len)

    up = (d.close > d.ema_t) & (d.ema_f > d.ema_s) & (d.ema_s > d.ema_t)
    dn = (d.close < d.ema_t) & (d.ema_f < d.ema_s) & (d.ema_s < d.ema_t)
    strong = d.adx >= p.adx_min
    d["long_sig"] = up & strong & (d.low <= d.ema_f) & (d.close > d.ema_f) & (d.close > d.open)
    d["short_sig"] = dn & strong & (d.high >= d.ema_f) & (d.close < d.ema_f) & (d.close < d.open)

    hours = d.index.hour
    in_window = (hours >= p.session_start_hour) & (hours < p.session_end_hour)
    d["in_session"] = in_window if p.use_session else True
    d["friday_cut"] = ((d.index.dayofweek == 4) & (hours >= 20)) if p.flat_friday else False
    d["cross_dn_trend"] = (d.close < d.ema_t) & (d.close.shift() >= d.ema_t.shift())
    d["cross_up_trend"] = (d.close > d.ema_t) & (d.close.shift() <= d.ema_t.shift())

    warmup = max(p.trend_len, p.atr_len, 2 * p.adx_len)
    d.iloc[:warmup, d.columns.get_indexer(["long_sig", "short_sig"])] = False
    return d


def _intrabar_exit(side: int, o: float, h: float, low: float, stop: float, target: float):
    """Return (price, reason) if stop/target is hit within this bar, else None."""
    if side > 0:
        if o <= stop:
            return o, "stop"
        if o >= target:
            return o, "target"
        hit_s, hit_t = low <= stop, h >= target
    else:
        if o >= stop:
            return o, "stop"
        if o <= target:
            return o, "target"
        hit_s, hit_t = h >= stop, low <= target
    if hit_s and hit_t:
        high_first = abs(h - o) < abs(o - low)
        # long: high first -> target first; short: high first -> stop first
        if side > 0:
            return (target, "target") if high_first else (stop, "stop")
        return (stop, "stop") if high_first else (target, "target")
    if hit_s:
        return stop, "stop"
    if hit_t:
        return target, "target"
    return None


def run(df: pd.DataFrame, p: Params | None = None) -> Result:
    p = p or Params()
    d = compute_signals(df, p)
    O, H, L, C = (d[c].to_numpy() for c in ("open", "high", "low", "close"))
    times = d.index
    days = times.normalize()

    cash = p.initial_capital
    trades: list[Trade] = []
    pos: Optional[Trade] = None
    pending_entry: Optional[tuple[int, int, float]] = None   # side, units, stop distance
    pending_close: Optional[str] = None
    equity = np.empty(len(d))

    cur_day = None
    day_start_eq = cash
    day_orders = 0
    halted = False

    def close_pos(i: int, price: float, reason: str) -> None:
        nonlocal pos, cash, day_orders
        assert pos is not None
        pnl = (price - pos.entry_price) * pos.side * pos.units - p.commission_per_unit * pos.units
        cash += pnl
        pos.exit_time, pos.exit_price, pos.exit_reason = times[i], price, reason
        pos.pnl += pnl
        trades.append(pos)
        pos = None
        day_orders += 1

    for i in range(len(d)):
        if days[i] != cur_day:
            cur_day, halted, day_orders = days[i], False, 0
            day_start_eq = cash + (((C[i - 1] - pos.entry_price) * pos.side * pos.units) if pos and i else 0)

        # 1) orders queued at previous close fill at this open
        if pending_close and pos is not None:
            close_pos(i, O[i], pending_close)
        pending_close = None
        if pending_entry and pos is None and not halted:
            side, units, sd = pending_entry
            fill = O[i]
            pos = Trade(side, units, times[i], fill, fill - side * sd, fill + side * sd * p.rr,
                        risk_cash=units * sd)
            pos.pnl = -p.commission_per_unit * units
            cash -= p.commission_per_unit * units
            day_orders += 1
        pending_entry = None

        # 2) intrabar stop / target
        if pos is not None:
            hit = _intrabar_exit(pos.side, O[i], H[i], L[i], pos.stop, pos.target)
            if hit:
                close_pos(i, *hit)

        # 3) bar-close bookkeeping and risk guards
        open_pnl = (C[i] - pos.entry_price) * pos.side * pos.units if pos else 0.0
        equity[i] = cash + open_pnl
        if not halted and day_start_eq > 0 and \
                (day_start_eq - equity[i]) / day_start_eq * 100 >= p.max_day_loss_pct:
            halted = True
            if pos is not None:
                pending_close = "day_loss_halt"
        if day_orders >= p.max_day_orders:
            halted = True

        # 4) exit rules evaluated on close
        row = d.iloc[i]
        if pos is not None and pending_close is None:
            if pos.side > 0 and row.cross_dn_trend:
                pending_close = "trend"
            elif pos.side < 0 and row.cross_up_trend:
                pending_close = "trend"
            elif row.friday_cut:
                pending_close = "weekend"

        # 5) entries evaluated on close (only when flat)
        if pos is None and not halted and row.in_session and not row.friday_cut and \
                (row.long_sig or row.short_sig) and row.atr > 0:
            sd = row.atr * p.sl_atr
            units = int(min(p.max_units, np.floor(equity[i] * p.risk_pct / 100 / sd)))
            if units >= 1:
                pending_entry = (1 if row.long_sig else -1, units, sd)

    if pos is not None:   # mark open trade out at the last close for reporting
        close_pos(len(d) - 1, C[-1], "end_of_data")
        equity[-1] = cash

    res = Result(trades, pd.Series(equity, index=times, name="equity"), p)
    res.stats = compute_stats(res)
    return res


def compute_stats(res: Result) -> dict:
    eq = res.equity
    p = res.params
    pnls = np.array([t.pnl for t in res.trades])
    wins, losses = pnls[pnls > 0], pnls[pnls <= 0]
    peak = eq.cummax()
    dd = ((eq - peak) / peak).min() if len(eq) else 0.0
    daily = eq.resample("1D").last().dropna().pct_change().dropna()
    sharpe = float(daily.mean() / daily.std() * np.sqrt(252)) if len(daily) > 1 and daily.std() > 0 else 0.0
    return {
        "start": str(eq.index[0]) if len(eq) else "",
        "end": str(eq.index[-1]) if len(eq) else "",
        "initial_capital": p.initial_capital,
        "final_equity": round(float(eq.iloc[-1]), 2) if len(eq) else p.initial_capital,
        "net_profit": round(float(pnls.sum()), 2),
        "return_pct": round(float(pnls.sum()) / p.initial_capital * 100, 2),
        "trades": int(len(pnls)),
        "win_rate_pct": round(len(wins) / len(pnls) * 100, 1) if len(pnls) else 0.0,
        "profit_factor": round(float(wins.sum() / -losses.sum()), 2) if losses.sum() < 0 else float("inf") if len(wins) else 0.0,
        "avg_r": round(float(np.mean([t.r_multiple for t in res.trades])), 2) if res.trades else 0.0,
        "max_drawdown_pct": round(float(dd) * 100, 2),
        "sharpe_daily": round(sharpe, 2),
    }
