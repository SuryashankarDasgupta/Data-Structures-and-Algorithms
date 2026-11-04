"""Bridge-side risk manager. These limits apply even if the alert source (Pine script or scanner) is wrong."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from backtest.markets import default_spec, round_qty

from .journal import Journal


@dataclass
class RiskDecision:
    allowed: bool
    units: float = 0.0
    reason: str = ""


class RiskManager:
    def __init__(self, cfg, journal: Journal, news=None):
        self.cfg = cfg
        self.journal = journal
        self.news = news            # NewsCalendar or None

    def day_start_balance(self, day: str, current_balance: float) -> float:
        key = f"day_start_balance:{day}"
        val = self.journal.get(key)
        if val is None:
            self.journal.set(key, str(current_balance))
            return current_balance
        return float(val)

    def check_entry(self, sig, balance: float, has_position: bool, now: datetime,
                    positions: Iterable = ()) -> RiskDecision:
        """`positions`: all open positions (any symbol) for portfolio limits."""
        positions = list(positions)
        day = now.date().isoformat()
        spec = default_spec(sig.symbol, getattr(self.cfg, "fx_shorts", True), getattr(self.cfg, "crypto_shorts", False))
        if os.path.exists(self.cfg.kill_switch_file):
            return RiskDecision(False, reason="kill switch active")
        if has_position:
            return RiskDecision(False, reason="position already open")
        if sig.side < 0 and not spec.allow_shorts:
            return RiskDecision(False, reason=f"shorts not allowed for {sig.symbol}")
        if self.news is not None and self.cfg.news_block_hours > 0 and spec.usd_news:
            hits = self.news.upcoming(now, self.cfg.news_block_hours, self.cfg.news_block_after_min)
            if hits:
                return RiskDecision(False, reason="high-impact news: " + ", ".join(e.label() for e in hits))
        if len(positions) >= self.cfg.max_positions:
            return RiskDecision(False, reason=f"max open positions ({self.cfg.max_positions}) reached")
        if self.journal.entries_on(day) >= self.cfg.max_trades_per_day:
            return RiskDecision(False, reason="max trades per day reached")

        start = self.day_start_balance(day, balance)
        if start > 0 and (start - balance) / start * 100 >= self.cfg.max_daily_loss_pct:
            return RiskDecision(False, reason="daily loss limit reached")

        units = sig.qty
        if sig.symbol == "XAUUSD":
            units = min(units, self.cfg.max_units)
        units = min(units, balance * self.cfg.max_risk_pct / 100 / sig.sl_dist)
        units = min(units, balance * self.cfg.max_leverage / sig.ref_price)
        gross = sum(abs(p.units) * p.avg_price for p in positions)
        room = balance * self.cfg.max_gross_leverage - gross
        units = min(units, max(room, 0.0) / sig.ref_price)
        units = round_qty(sig.symbol, units)
        if units <= 0:
            return RiskDecision(False, reason="position size below the minimum order after risk caps")
        note = "" if abs(units - sig.qty) < 1e-12 else f"qty capped {sig.qty:g}->{units:g}"
        return RiskDecision(True, units=units, reason=note)
