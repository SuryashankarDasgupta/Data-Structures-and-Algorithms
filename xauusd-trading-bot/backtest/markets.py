"""Market definitions shared by the backtester, the 24/7 scanner and the bridge.

Default universe = XAUUSD + BTCUSD + ETHUSD. In the 2006-2026 research, a 12-pair forex portfolio made money in
2006-2015 only with deep drawdowns (-26%) and lost heavily in 2016-2026 (-5.5%/yr, -57% drawdown), while gold and
the two largest cryptocurrencies were profitable in both periods. Forex and other coins remain opt-in markets.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

CRYPTO = {"BTCUSD", "ETHUSD", "XRPUSD", "SOLUSD", "BNBUSD", "ADAUSD", "DOGEUSD", "LTCUSD"}
FX_MAJORS = {"EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD"}
FX_CROSSES = {"EURJPY", "GBPJPY", "EURGBP", "AUDJPY", "EURCHF"}
FX = FX_MAJORS | FX_CROSSES
METALS = {"XAUUSD"}
ALL_MARKETS = CRYPTO | FX | METALS
DEFAULT_UNIVERSE = ("XAUUSD", "BTCUSD", "ETHUSD")

# Smallest order increment per market (broker/exchange dependent; adjust to yours)
QTY_STEP = {"XAUUSD": 1.0, "BTCUSD": 0.0001, "ETHUSD": 0.001, "XRPUSD": 1.0, "SOLUSD": 0.01,
            "BNBUSD": 0.001, "ADAUSD": 1.0, "DOGEUSD": 10.0, "LTCUSD": 0.01}
FX_QTY_STEP = 1000.0           # units of base currency (a micro lot)

# Symbol names per data source / broker
YAHOO = {"XAUUSD": "GC=F", **{s: f"{s}=X" for s in FX}, **{s: f"{s[:-3]}-USD" for s in CRYPTO}}
COINBASE = {s: f"{s[:-3]}-USD" for s in CRYPTO}
OANDA = {"XAUUSD": "XAU_USD", **{s: f"{s[:3]}_{s[3:]}" for s in FX}}


@dataclass(frozen=True)
class MarketSpec:
    symbol: str
    asset_class: str            # fx | metal | crypto
    cost_pct: float             # per side, % of notional (spread + fees)
    allow_shorts: bool
    usd_news: bool              # apply the USD high-impact news filter

    def with_shorts(self, allow: bool) -> "MarketSpec":
        return replace(self, allow_shorts=allow)


def default_spec(symbol: str, fx_shorts: bool = True, crypto_shorts: bool = False) -> MarketSpec:
    s = symbol.upper()
    if s in CRYPTO:
        return MarketSpec(s, "crypto", 0.10, crypto_shorts, False)
    if s in METALS:
        return MarketSpec(s, "metal", 0.01, False, True)
    if s in FX_MAJORS:
        return MarketSpec(s, "fx", 0.01, fx_shorts, "USD" in s)
    if s in FX_CROSSES:
        return MarketSpec(s, "fx", 0.015, fx_shorts, "USD" in s)
    raise ValueError(f"unknown market {symbol!r}; supported: {', '.join(sorted(ALL_MARKETS))}")


def qty_step(symbol: str) -> float:
    s = symbol.upper()
    if s in FX:
        return FX_QTY_STEP
    return QTY_STEP.get(s, 1.0)


def round_qty(symbol: str, qty: float) -> float:
    """Round a quantity DOWN to the market's order step (never rounds risk up)."""
    step = qty_step(symbol)
    n = int(qty / step + 1e-9)
    return round(n * step, 10)
