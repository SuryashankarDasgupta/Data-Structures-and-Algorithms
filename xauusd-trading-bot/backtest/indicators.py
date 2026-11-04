"""Indicators implemented to match TradingView's built-ins (ta.ema, ta.rma, ta.atr, ta.dmi)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def ema(src: pd.Series, length: int) -> pd.Series:
    return src.ewm(span=length, adjust=False).mean()


def rma(src: pd.Series, length: int) -> pd.Series:
    """Wilder's moving average, seeded with an SMA like ta.rma."""
    vals = src.to_numpy(dtype=float)
    out = np.full(len(vals), np.nan)
    alpha = 1.0 / length
    valid = np.flatnonzero(~np.isnan(vals))
    if len(valid) < length:
        return pd.Series(out, index=src.index)
    start = valid[0] + length - 1
    out[start] = np.nanmean(vals[valid[0]:start + 1])
    for i in range(start + 1, len(vals)):
        v = vals[i] if not np.isnan(vals[i]) else 0.0
        out[i] = alpha * v + (1 - alpha) * out[i - 1]
    return pd.Series(out, index=src.index)


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["close"].shift()
    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - prev_close).abs(),
                    (df["low"] - prev_close).abs()], axis=1).max(axis=1)
    tr.iloc[0] = df["high"].iloc[0] - df["low"].iloc[0]
    return tr


def atr(df: pd.DataFrame, length: int) -> pd.Series:
    return rma(true_range(df), length)


def adx(df: pd.DataFrame, di_len: int, adx_len: int) -> pd.Series:
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    plus_dm.iloc[0] = minus_dm.iloc[0] = np.nan
    tr = rma(true_range(df), di_len)
    plus = (100 * rma(plus_dm, di_len) / tr).ffill()
    minus = (100 * rma(minus_dm, di_len) / tr).ffill()
    s = (plus + minus).replace(0, 1)
    return 100 * rma((plus - minus).abs() / s, adx_len)
