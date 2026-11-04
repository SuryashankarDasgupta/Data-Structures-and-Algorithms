"""Bridge-side risk manager. These limits apply even if the Pine script is misconfigured."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime

from .journal import Journal


@dataclass
class RiskDecision:
    allowed: bool
    units: int = 0
    reason: str = ""


class RiskManager:
    def __init__(self, cfg, journal: Journal):
        self.cfg = cfg
        self.journal = journal

    def day_start_balance(self, day: str, current_balance: float) -> float:
        key = f"day_start_balance:{day}"
        val = self.journal.get(key)
        if val is None:
            self.journal.set(key, str(current_balance))
            return current_balance
        return float(val)

    def check_entry(self, sig, balance: float, has_position: bool, now: datetime) -> RiskDecision:
        day = now.date().isoformat()
        if os.path.exists(self.cfg.kill_switch_file):
            return RiskDecision(False, reason="kill switch active")
        if has_position:
            return RiskDecision(False, reason="position already open")
        if self.journal.entries_on(day) >= self.cfg.max_trades_per_day:
            return RiskDecision(False, reason="max trades per day reached")

        start = self.day_start_balance(day, balance)
        if start > 0 and (start - balance) / start * 100 >= self.cfg.max_daily_loss_pct:
            return RiskDecision(False, reason="daily loss limit reached")

        units = min(sig.qty, self.cfg.max_units)
        max_risk_cash = balance * self.cfg.max_risk_pct / 100
        units = min(units, int(max_risk_cash // sig.sl_dist))
        if units < 1:
            return RiskDecision(False, reason="position size below 1 oz after risk caps")
        note = "" if units == sig.qty else f"qty capped {sig.qty}->{units}"
        return RiskDecision(True, units=units, reason=note)
