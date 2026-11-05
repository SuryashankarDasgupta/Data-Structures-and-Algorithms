"""Chart-pattern signals shared by the backtester and the live scanner.

resistance_breaks: the close crosses above a resistance level touched by at least two swing highs that lie
within `tol_atr` x ATR of each other. Swing highs are pivots (highest high of the surrounding `pivot` bars on
each side) and are only used once confirmed, i.e. `pivot` bars after they formed, so there is no lookahead.

Research (Nov 2026, gold + BTC + ETH, tuning 2006-2020 vs unseen 2021-2026): adding these entries to the 20-day
breakout improved both periods in all 27 settings tested (pivot 2/3/5, tolerance 0.3/0.5/0.8 ATR, lookback
100/150/250 days). Most of the gain came from gold. Double bottoms, inverse head & shoulders, cup & handle,
bull flags, ascending triangles and support bounces were also tested and not adopted (see README).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def swing_highs(high: np.ndarray, pivot: int) -> list[tuple[int, int, float]]:
    """(confirmed_at, index, price) for every pivot high."""
    n = len(high)
    return [(i + pivot, i, float(high[i])) for i in range(pivot, n - pivot)
            if high[i] == high[i - pivot:i + pivot + 1].max()]


def resistance_breaks(df: pd.DataFrame, atr: pd.Series, pivot: int = 3, tol_atr: float = 0.5,
                      lookback: int = 150, max_pivots: int = 8) -> pd.Series:
    """True on bars whose close crosses above a resistance touched by >= 2 confirmed swing highs."""
    H = df["high"].to_numpy(float)
    C = df["close"].to_numpy(float)
    A = atr.to_numpy(float)
    n = len(df)
    piv = swing_highs(H, pivot)
    out = np.zeros(n, dtype=bool)
    known: list[tuple[int, float]] = []
    p = 0
    for i in range(1, n):
        while p < len(piv) and piv[p][0] <= i:
            known.append(piv[p][1:])
            p += 1
        a = A[i]
        if not a > 0:
            continue
        hs = [(j, v) for j, v in known[-max_pivots:] if i - j <= lookback]
        for x in range(len(hs)):
            for y in range(x + 1, len(hs)):
                if abs(hs[x][1] - hs[y][1]) <= tol_atr * a:
                    level = max(hs[x][1], hs[y][1])
                    if C[i] > level >= C[i - 1]:
                        out[i] = True
    return pd.Series(out, index=df.index)
