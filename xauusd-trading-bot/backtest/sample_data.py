"""Generate SYNTHETIC gold-like OHLC data for smoke tests. Not real market data."""
from __future__ import annotations

import numpy as np
import pandas as pd


def synthetic_xauusd(bars: int = 5000, freq: str = "1h", start_price: float = 2000.0,
                     seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=bars * 2, freq=freq, tz="UTC")
    idx = idx[idx.day_of_week < 5][:bars]             # drop weekends
    # regime-switching drift so trends exist, ~0.25% hourly vol
    regime = np.repeat(rng.choice([-1, 0, 1], size=bars // 250 + 1), 250)[:bars]
    rets = rng.normal(regime * 0.0003, 0.0025, size=bars)
    close = start_price * np.exp(np.cumsum(rets))
    open_ = np.concatenate([[start_price], close[:-1]]) * (1 + rng.normal(0, 0.0003, bars))
    spread = np.abs(rng.normal(0, 0.0018, bars)) * close
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=idx)
