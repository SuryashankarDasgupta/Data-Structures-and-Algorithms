"""Bar-by-bar simulation of pine/xauusd_daily_trend.pine.

Fill model (mirrors TradingView's broker emulator):
  * signals are evaluated on bar close; market orders fill at the next bar's open
  * the initial stop is set from the signal bar's close (exactly like the Pine script) and is
    active on the fill bar; afterwards it trails at  highest-high-since-entry - trail_atr x ATR
    (lowest-low + ... for shorts) and never loosens
  * a bar that opens through the stop fills at the open, otherwise at the stop price
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
    fast_len: int = 20
    slow_len: int = 200
    allow_shorts: bool = False
    atr_len: int = 14
    init_atr: float = 2.0
    trail_atr: float = 2.5
    risk_pct: float = 1.0
    max_lev: float = 1.0
    qty_step: float = 1.0
    initial_capital: float = 25_000.0
    commission_per_unit: float = 0.15


@dataclass
class Trade:
    side: int
    units: float
    entry_time: pd.Timestamp
    entry_price: float
    initial_stop: float
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
    stops: pd.Series
    params: Params
    stats: dict = field(default_factory=dict)

    def trades_frame(self) -> pd.DataFrame:
        return pd.DataFrame([{**asdict(t), "r_multiple": t.r_multiple} for t in self.trades])


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
    out = out[(out.high >= out.low) & (out.open > 0)]
    return out[~out.index.duplicated(keep="last")].sort_index()


def compute_signals(df: pd.DataFrame, p: Params) -> pd.DataFrame:
    d = df.copy()
    d["ema_f"] = ind.ema(d["close"], p.fast_len)
    d["ema_s"] = ind.ema(d["close"], p.slow_len)
    d["atr"] = ind.atr(d, p.atr_len)
    d["up"] = d.ema_f > d.ema_s
    d["dn"] = d.ema_f < d.ema_s
    d["long_sig"] = d.up & (d.close > d.ema_f)
    d["short_sig"] = (d.dn & (d.close < d.ema_f)) if p.allow_shorts else False
    warmup = max(p.slow_len, p.atr_len)
    d.iloc[:warmup, d.columns.get_indexer(["long_sig", "short_sig"])] = False
    return d


def _stop_fill(side: int, o: float, h: float, low: float, stop: float) -> Optional[float]:
    """Price at which a stop order fills within this bar, or None."""
    if side > 0:
        if o <= stop:
            return o
        return stop if low <= stop else None
    if o >= stop:
        return o
    return stop if h >= stop else None


def run(df: pd.DataFrame, p: Params | None = None) -> Result:
    p = p or Params()
    d = compute_signals(df, p)
    O, H, L, C, A = (d[c].to_numpy(dtype=float) for c in ("open", "high", "low", "close", "atr"))
    up, dn = d["up"].to_numpy(), d["dn"].to_numpy()
    long_sig, short_sig = d["long_sig"].to_numpy(dtype=bool), d["short_sig"].to_numpy(dtype=bool)
    times = d.index
    n = len(d)

    cash = p.initial_capital
    fee = p.commission_per_unit
    trades: list[Trade] = []
    pos: Optional[Trade] = None
    stop = np.nan
    extreme = np.nan
    pending_entry: Optional[tuple[int, float, float]] = None   # side, units, stop distance
    pending_close: Optional[str] = None
    equity = np.empty(n)
    stops = np.full(n, np.nan)

    def close_pos(i: int, price: float, reason: str) -> None:
        nonlocal pos, cash
        pnl = (price - pos.entry_price) * pos.side * pos.units - fee * pos.units
        cash += pnl
        pos.exit_time, pos.exit_price, pos.exit_reason = times[i], price, reason
        pos.pnl += pnl
        trades.append(pos)
        pos = None

    for i in range(n):
        # 1) market orders queued at the previous close fill at this open
        if pending_close and pos is not None:
            close_pos(i, O[i], pending_close)
        pending_close = None
        if pending_entry and pos is None:
            side, units, sd = pending_entry
            pos = Trade(side, units, times[i], O[i], stop, risk_cash=units * sd, pnl=-fee * units)
            cash -= fee * units
        pending_entry = None

        # 2) stop order (active on the fill bar too)
        if pos is not None:
            px = _stop_fill(pos.side, O[i], H[i], L[i], stop)
            if px is not None:
                close_pos(i, px, "trailing_stop" if stop != pos.initial_stop else "initial_stop")

        # 3) bar close: trail the stop
        if pos is not None:
            if pos.side > 0:
                extreme = H[i] if np.isnan(extreme) else max(extreme, H[i])
                stop = max(stop, extreme - p.trail_atr * A[i])
            else:
                extreme = L[i] if np.isnan(extreme) else min(extreme, L[i])
                stop = min(stop, extreme + p.trail_atr * A[i])
            stops[i] = stop
        else:
            extreme = np.nan

        open_pnl = (C[i] - pos.entry_price) * pos.side * pos.units if pos else 0.0
        equity[i] = cash + open_pnl

        # 4) trend exit -> next open
        if pos is not None and ((pos.side > 0 and dn[i]) or (pos.side < 0 and up[i])):
            pending_close = "trend"

        # 5) entry when flat
        if pos is None and (long_sig[i] or short_sig[i]) and A[i] > 0:
            sd = A[i] * p.init_atr
            raw = min(equity[i] * p.risk_pct / 100 / sd, equity[i] * p.max_lev / C[i])
            units = np.floor(raw / p.qty_step + 1e-9) * p.qty_step
            if units >= p.qty_step:
                side = 1 if long_sig[i] else -1
                stop = C[i] - side * sd
                pending_entry = (side, float(units), sd)

    if pos is not None:   # mark open trade out at the last close for reporting
        close_pos(n - 1, C[-1], "end_of_data")
        equity[-1] = cash

    res = Result(trades, pd.Series(equity, index=times, name="equity"),
                 pd.Series(stops, index=times, name="stop"), p)
    res.stats = compute_stats(res)
    return res


def compute_stats(res: Result) -> dict:
    eq = res.equity
    p = res.params
    pnls = np.array([t.pnl for t in res.trades])
    wins, losses = pnls[pnls > 0], pnls[pnls <= 0]
    dd = float((eq / eq.cummax() - 1).min()) if len(eq) else 0.0
    years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9) if len(eq) else 1.0
    final = float(eq.iloc[-1]) if len(eq) else p.initial_capital
    cagr = (final / p.initial_capital) ** (1 / years) - 1 if final > 0 else -1.0
    daily = eq.resample("1D").last().dropna().pct_change().dropna()
    sharpe = float(daily.mean() / daily.std() * np.sqrt(252)) if len(daily) > 1 and daily.std() > 0 else 0.0
    in_mkt = sum(((t.exit_time - t.entry_time).days for t in res.trades), 0) / max(years * 365.25, 1)
    if losses.sum() < 0:
        pf = round(float(wins.sum() / -losses.sum()), 2)
    else:
        pf = float("inf") if len(wins) else 0.0
    return {
        "start": str(eq.index[0].date()) if len(eq) else "",
        "end": str(eq.index[-1].date()) if len(eq) else "",
        "initial_capital": p.initial_capital,
        "final_equity": round(final, 2),
        "net_profit": round(float(pnls.sum()), 2),
        "return_pct": round(float(pnls.sum()) / p.initial_capital * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "max_drawdown_pct": round(dd * 100, 2),
        "return_to_drawdown": round(cagr / abs(dd), 2) if dd < 0 else float("inf"),
        "trades": int(len(pnls)),
        "win_rate_pct": round(len(wins) / len(pnls) * 100, 1) if len(pnls) else 0.0,
        "profit_factor": pf,
        "avg_r": round(float(np.mean([t.r_multiple for t in res.trades])), 2) if res.trades else 0.0,
        "time_in_market_pct": round(in_mkt * 100, 1),
        "sharpe_daily": round(sharpe, 2),
    }
