"""Configuration loaded from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

LIVE_CONFIRMATION = "yes-i-understand-the-risk"


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass
class Config:
    webhook_secret: str = ""
    host: str = "0.0.0.0"
    port: int = 8080

    broker: str = "paper"              # "paper" | "oanda"
    allowed_symbols: tuple[str, ...] = ("XAUUSD",)

    # Risk limits enforced by the bridge (independent of the Pine script)
    max_units: int = 100               # ounces
    max_risk_pct: float = 1.5          # max % of balance at risk per trade (qty * sl_dist)
    max_leverage: float = 1.0          # max notional (units * price) as a multiple of balance
    max_daily_loss_pct: float = 3.0    # stop opening trades after this % drawdown from day start
    max_trades_per_day: int = 4
    max_signal_delay_s: int = 120      # reject alerts older than bar close + this
    kill_switch_file: str = "KILL_SWITCH"
    ip_allowlist: tuple[str, ...] = ()  # empty = allow any

    # Paper broker
    paper_start_balance: float = 10_000.0
    paper_spread: float = 0.30         # USD per oz, full spread
    paper_state_file: str = "paper_state.json"

    # OANDA v20
    oanda_env: str = "practice"        # "practice" | "live"
    oanda_account_id: str = ""
    oanda_token: str = ""
    allow_live_trading: str = ""

    journal_path: str = "journal.sqlite3"
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "Config":
        def tup(name: str, default: str) -> tuple[str, ...]:
            return tuple(s.strip() for s in _env(name, default).split(",") if s.strip())

        return cls(
            webhook_secret=_env("WEBHOOK_SECRET", ""),
            host=_env("BRIDGE_HOST", "0.0.0.0"),
            port=int(_env("BRIDGE_PORT", "8080")),
            broker=_env("BROKER", "paper").lower(),
            allowed_symbols=tup("ALLOWED_SYMBOLS", "XAUUSD"),
            max_units=int(_env("MAX_UNITS", "100")),
            max_risk_pct=float(_env("MAX_RISK_PCT", "1.5")),
            max_leverage=float(_env("MAX_LEVERAGE", "1.0")),
            max_daily_loss_pct=float(_env("MAX_DAILY_LOSS_PCT", "3.0")),
            max_trades_per_day=int(_env("MAX_TRADES_PER_DAY", "4")),
            max_signal_delay_s=int(_env("MAX_SIGNAL_DELAY_S", "120")),
            kill_switch_file=_env("KILL_SWITCH_FILE", "KILL_SWITCH"),
            ip_allowlist=tup("IP_ALLOWLIST", ""),
            paper_start_balance=float(_env("PAPER_START_BALANCE", "10000")),
            paper_spread=float(_env("PAPER_SPREAD", "0.30")),
            paper_state_file=_env("PAPER_STATE_FILE", "paper_state.json"),
            oanda_env=_env("OANDA_ENV", "practice").lower(),
            oanda_account_id=_env("OANDA_ACCOUNT_ID", ""),
            oanda_token=_env("OANDA_TOKEN", ""),
            allow_live_trading=_env("ALLOW_LIVE_TRADING", ""),
            journal_path=_env("JOURNAL_PATH", "journal.sqlite3"),
        )

    def validate(self) -> None:
        if len(self.webhook_secret) < 16:
            raise ValueError("WEBHOOK_SECRET must be set and at least 16 characters long")
        if self.broker not in ("paper", "oanda"):
            raise ValueError(f"Unknown BROKER {self.broker!r}")
        if self.broker == "oanda":
            if not (self.oanda_account_id and self.oanda_token):
                raise ValueError("OANDA_ACCOUNT_ID and OANDA_TOKEN are required for BROKER=oanda")
            if self.oanda_env not in ("practice", "live"):
                raise ValueError("OANDA_ENV must be 'practice' or 'live'")
            if self.oanda_env == "live" and self.allow_live_trading != LIVE_CONFIRMATION:
                raise ValueError(
                    f"Live trading refused: set ALLOW_LIVE_TRADING={LIVE_CONFIRMATION} to enable it"
                )
