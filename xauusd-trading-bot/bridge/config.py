"""Configuration loaded from environment variables."""
from __future__ import annotations

import ipaddress
import os
import re
from dataclasses import dataclass, field

LIVE_CONFIRMATION = "yes-i-understand-the-risk"


def is_loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


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
    max_risk_pct: float = 2.5          # max % of balance at risk per trade (qty * sl_dist)
    max_leverage: float = 1.0          # max notional (units * price) as a multiple of balance
    max_daily_loss_pct: float = 5.0    # stop opening trades after this % drawdown from day start
    max_trades_per_day: int = 4
    max_signal_delay_s: int = 120      # reject alerts older than bar close + this
    kill_switch_file: str = "KILL_SWITCH"
    ip_allowlist: tuple[str, ...] = ()  # IPs or CIDR ranges; empty = allow any
    # Header carrying the real client IP, trusted only on requests from a loopback peer (a local proxy such
    # as cloudflared). "" = trust no header. Cloudflare sets CF-Connecting-IP and overwrites client values.
    trusted_ip_header: str = ""

    # Paper broker
    paper_start_balance: float = 10_000.0
    paper_spread: float = 0.30         # USD per oz, full spread
    paper_state_file: str = "paper_state.json"

    # OANDA v20
    oanda_env: str = "practice"        # "practice" | "live"
    oanda_account_id: str = ""
    oanda_token: str = ""
    allow_live_trading: str = ""

    # High-impact news guard: reject new entries within this many hours before a release (0 = off)
    news_block_hours: float = 24.0
    news_block_after_min: float = 30.0   # ...and for this many minutes after it
    news_events: tuple[str, ...] = ("FOMC", "NFP", "CPI")
    news_calendar: str = ""              # empty = bundled data/high_impact_usd.csv

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
            max_risk_pct=float(_env("MAX_RISK_PCT", "2.5")),
            max_leverage=float(_env("MAX_LEVERAGE", "1.0")),
            max_daily_loss_pct=float(_env("MAX_DAILY_LOSS_PCT", "5.0")),
            max_trades_per_day=int(_env("MAX_TRADES_PER_DAY", "4")),
            max_signal_delay_s=int(_env("MAX_SIGNAL_DELAY_S", "120")),
            kill_switch_file=_env("KILL_SWITCH_FILE", "KILL_SWITCH"),
            ip_allowlist=tup("IP_ALLOWLIST", ""),
            trusted_ip_header=_env("TRUSTED_IP_HEADER", "").strip(),
            paper_start_balance=float(_env("PAPER_START_BALANCE", "10000")),
            paper_spread=float(_env("PAPER_SPREAD", "0.30")),
            paper_state_file=_env("PAPER_STATE_FILE", "paper_state.json"),
            oanda_env=_env("OANDA_ENV", "practice").lower(),
            oanda_account_id=_env("OANDA_ACCOUNT_ID", ""),
            oanda_token=_env("OANDA_TOKEN", ""),
            allow_live_trading=_env("ALLOW_LIVE_TRADING", ""),
            news_block_hours=float(_env("NEWS_BLOCK_HOURS", "24")),
            news_block_after_min=float(_env("NEWS_BLOCK_AFTER_MIN", "30")),
            news_events=tup("NEWS_EVENTS", "FOMC,NFP,CPI"),
            news_calendar=_env("NEWS_CALENDAR", ""),
            journal_path=_env("JOURNAL_PATH", "journal.sqlite3"),
        )

    def validate(self) -> None:
        if len(self.webhook_secret) < 16:
            raise ValueError("WEBHOOK_SECRET must be set and at least 16 characters long")
        if self.broker not in ("paper", "oanda"):
            raise ValueError(f"Unknown BROKER {self.broker!r}")
        if self.trusted_ip_header and not re.fullmatch(r"[A-Za-z0-9-]+", self.trusted_ip_header):
            raise ValueError("TRUSTED_IP_HEADER must be a single header name, e.g. CF-Connecting-IP")
        self.allowlist_networks()          # raises on a bad IP_ALLOWLIST entry
        if self.broker == "oanda":
            if not (self.oanda_account_id and self.oanda_token):
                raise ValueError("OANDA_ACCOUNT_ID and OANDA_TOKEN are required for BROKER=oanda")
            if self.oanda_env not in ("practice", "live"):
                raise ValueError("OANDA_ENV must be 'practice' or 'live'")
            if self.oanda_env == "live" and self.allow_live_trading != LIVE_CONFIRMATION:
                raise ValueError(
                    f"Live trading refused: set ALLOW_LIVE_TRADING={LIVE_CONFIRMATION} to enable it"
                )

    def allowlist_networks(self) -> list:
        try:
            return [ipaddress.ip_network(e, strict=False) for e in self.ip_allowlist]
        except ValueError as exc:
            raise ValueError(f"IP_ALLOWLIST: {exc}") from None

    def warnings(self) -> list[str]:
        """Settings that are valid but almost certainly not what the user wants."""
        out = []
        if self.ip_allowlist and is_loopback(self.host) and not self.trusted_ip_header:
            out.append("IP_ALLOWLIST is set but the bridge listens on loopback with no TRUSTED_IP_HEADER: every "
                       "request will appear to come from 127.0.0.1 and be rejected. Behind cloudflared, set "
                       "TRUSTED_IP_HEADER=CF-Connecting-IP.")
        return out
