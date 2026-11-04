"""Configuration loaded from environment variables."""
from __future__ import annotations

import ipaddress
import os
import re
from dataclasses import dataclass, field

LIVE_CONFIRMATION = "yes-i-understand-the-risk"
EXECUTION_MODES = ("sync", "async", "auto")


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
    allowed_symbols: tuple[str, ...] = ("XAUUSD", "BTCUSD", "ETHUSD")

    # Risk limits enforced by the bridge (independent of the Pine script)
    max_units: int = 100               # XAUUSD only: max ounces per position
    max_risk_pct: float = 2.5          # max % of balance at risk per trade (qty * sl_dist)
    max_leverage: float = 1.0          # max notional (units * price) as a multiple of balance
    max_daily_loss_pct: float = 5.0    # stop opening trades after this % drawdown from day start
    max_trades_per_day: int = 6
    max_positions: int = 4             # open positions across all markets
    max_gross_leverage: float = 3.0    # total notional of all positions / balance
    max_signal_delay_s: int = 120      # reject alerts older than bar close + this
    kill_switch_file: str = "KILL_SWITCH"
    ip_allowlist: tuple[str, ...] = ()  # IPs or CIDR ranges; empty = allow any
    # Header carrying the real client IP, trusted only on requests from a loopback peer (a local proxy such
    # as cloudflared). "" = trust no header. Cloudflare sets CF-Connecting-IP and overwrites client values.
    trusted_ip_header: str = ""

    # "sync" = place the order before answering the webhook; "async" = answer 202 at once and execute in a
    # background worker (TradingView gives up after ~3 s); "auto" = async for OANDA, sync for paper
    execution_mode: str = "auto"

    # Paper broker
    paper_start_balance: float = 10_000.0
    paper_spread: float = 0.30         # USD per oz, full spread
    paper_state_file: str = "paper_state.json"

    # OANDA v20
    oanda_env: str = "practice"        # "practice" | "live"
    oanda_account_id: str = ""
    oanda_token: str = ""
    allow_live_trading: str = ""
    oanda_timeout_s: float = 10.0        # per HTTP request

    # High-impact news guard: reject new entries within this many hours before a release (0 = off)
    news_block_hours: float = 24.0
    news_block_after_min: float = 30.0   # ...and for this many minutes after it
    news_events: tuple[str, ...] = ("FOMC", "NFP", "CPI")
    news_calendar: str = ""              # empty = bundled data/high_impact_usd.csv

    # 24/7 multi-market scanner (bridge/scanner.py): checks every market on a timer, acts on daily closes
    scanner_enabled: bool = False
    scan_interval_s: int = 300
    risk_pct: float = 1.0              # equity at risk per new position (initial stop distance)
    nonfx_feed: str = "auto"           # data for gold/forex: oanda | yahoo (paper only) | auto
    fx_shorts: bool = True
    crypto_shorts: bool = False

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
            allowed_symbols=tuple(s.upper() for s in tup("ALLOWED_SYMBOLS", "XAUUSD,BTCUSD,ETHUSD")),
            max_units=int(_env("MAX_UNITS", "100")),
            max_risk_pct=float(_env("MAX_RISK_PCT", "2.5")),
            max_leverage=float(_env("MAX_LEVERAGE", "1.0")),
            max_daily_loss_pct=float(_env("MAX_DAILY_LOSS_PCT", "5.0")),
            max_trades_per_day=int(_env("MAX_TRADES_PER_DAY", "6")),
            max_positions=int(_env("MAX_POSITIONS", "4")),
            max_gross_leverage=float(_env("MAX_GROSS_LEVERAGE", "3.0")),
            max_signal_delay_s=int(_env("MAX_SIGNAL_DELAY_S", "120")),
            kill_switch_file=_env("KILL_SWITCH_FILE", "KILL_SWITCH"),
            ip_allowlist=tup("IP_ALLOWLIST", ""),
            trusted_ip_header=_env("TRUSTED_IP_HEADER", "").strip(),
            execution_mode=_env("EXECUTION_MODE", "auto").strip().lower(),
            paper_start_balance=float(_env("PAPER_START_BALANCE", "10000")),
            paper_spread=float(_env("PAPER_SPREAD", "0.30")),
            paper_state_file=_env("PAPER_STATE_FILE", "paper_state.json"),
            oanda_env=_env("OANDA_ENV", "practice").lower(),
            oanda_account_id=_env("OANDA_ACCOUNT_ID", ""),
            oanda_token=_env("OANDA_TOKEN", ""),
            allow_live_trading=_env("ALLOW_LIVE_TRADING", ""),
            oanda_timeout_s=float(_env("OANDA_TIMEOUT_S", "10")),
            news_block_hours=float(_env("NEWS_BLOCK_HOURS", "24")),
            news_block_after_min=float(_env("NEWS_BLOCK_AFTER_MIN", "30")),
            news_events=tup("NEWS_EVENTS", "FOMC,NFP,CPI"),
            news_calendar=_env("NEWS_CALENDAR", ""),
            scanner_enabled=_env("SCANNER", "off").strip().lower() in ("1", "on", "true", "yes"),
            scan_interval_s=int(_env("SCAN_INTERVAL_S", "300")),
            risk_pct=float(_env("RISK_PCT", "1.0")),
            nonfx_feed=_env("NONFX_FEED", "auto").strip().lower(),
            fx_shorts=_env("FX_SHORTS", "on").strip().lower() in ("1", "on", "true", "yes"),
            crypto_shorts=_env("CRYPTO_SHORTS", "off").strip().lower() in ("1", "on", "true", "yes"),
            journal_path=_env("JOURNAL_PATH", "journal.sqlite3"),
        )

    def validate(self) -> None:
        if len(self.webhook_secret) < 16:
            raise ValueError("WEBHOOK_SECRET must be set and at least 16 characters long")
        if self.broker not in ("paper", "oanda"):
            raise ValueError(f"Unknown BROKER {self.broker!r}")
        if self.execution_mode not in EXECUTION_MODES:
            raise ValueError(f"EXECUTION_MODE must be one of {', '.join(EXECUTION_MODES)}")
        if self.oanda_timeout_s <= 0:
            raise ValueError("OANDA_TIMEOUT_S must be positive")
        if self.trusted_ip_header and not re.fullmatch(r"[A-Za-z0-9-]+", self.trusted_ip_header):
            raise ValueError("TRUSTED_IP_HEADER must be a single header name, e.g. CF-Connecting-IP")
        self.allowlist_networks()          # raises on a bad IP_ALLOWLIST entry
        from backtest.markets import ALL_MARKETS, CRYPTO
        unknown = sorted(set(self.allowed_symbols) - ALL_MARKETS)
        if unknown:
            raise ValueError(f"ALLOWED_SYMBOLS: unsupported market(s) {', '.join(unknown)}")
        if self.broker == "oanda" and set(self.allowed_symbols) & CRYPTO:
            raise ValueError("OANDA does not offer these cryptocurrencies: remove them from ALLOWED_SYMBOLS "
                             "or use BROKER=paper")
        if self.nonfx_feed not in ("auto", "oanda", "yahoo"):
            raise ValueError("NONFX_FEED must be auto, oanda or yahoo")
        if self.nonfx_feed == "yahoo" and self.broker != "paper":
            raise ValueError("NONFX_FEED=yahoo is an unofficial data source, allowed with BROKER=paper only")
        if not 0 < self.risk_pct <= self.max_risk_pct:
            raise ValueError("RISK_PCT must be positive and not above MAX_RISK_PCT")
        if self.scan_interval_s < 30:
            raise ValueError("SCAN_INTERVAL_S must be at least 30 seconds")
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

    def resolved_execution_mode(self) -> str:
        if self.execution_mode == "auto":
            return "async" if self.broker == "oanda" else "sync"
        return self.execution_mode

    def warnings(self) -> list[str]:
        """Settings that are valid but almost certainly not what the user wants."""
        out = []
        if self.ip_allowlist and is_loopback(self.host) and not self.trusted_ip_header:
            out.append("IP_ALLOWLIST is set but the bridge listens on loopback with no TRUSTED_IP_HEADER: every "
                       "request will appear to come from 127.0.0.1 and be rejected. Behind cloudflared, set "
                       "TRUSTED_IP_HEADER=CF-Connecting-IP.")
        from backtest.markets import FX
        fx = sorted(set(self.allowed_symbols) & FX)
        if fx:
            out.append(f"Forex markets enabled ({', '.join(fx)}): daily trend following on forex lost heavily in the "
                       "2016-2026 backtest (-5.5%/yr, -57% drawdown) after deep drawdowns in 2006-2015. "
                       "Consider removing them.")
        return out
