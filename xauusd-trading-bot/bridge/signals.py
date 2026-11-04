"""Parsing and validation of TradingView alert payloads."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

ENTRY_ACTIONS = {"buy", "sell"}
CLOSE_ACTIONS = {"close_long", "close_short", "close_all"}


class SignalError(ValueError):
    """Raised when a payload is malformed or fails validation."""


@dataclass(frozen=True)
class Signal:
    action: str
    symbol: str
    tf: str
    bar_time_ms: int
    ref_price: float
    qty: int = 0
    sl_dist: float = 0.0
    tp_dist: float = 0.0
    fill_price: Optional[float] = None   # {{strategy.order.price}} from TradingView
    reason: str = ""

    @property
    def is_entry(self) -> bool:
        return self.action in ENTRY_ACTIONS

    @property
    def side(self) -> int:
        return 1 if self.action == "buy" else -1

    @property
    def dedupe_key(self) -> str:
        return f"{self.symbol}:{self.tf}:{self.bar_time_ms}:{self.action}"


def tf_to_seconds(tf: str) -> int:
    """Convert a TradingView timeframe.period string to seconds."""
    tf = tf.strip().upper()
    if not tf:
        raise SignalError("empty timeframe")
    units = {"S": 1, "D": 86_400, "W": 604_800, "M": 2_592_000}
    if tf[-1] in units:
        n = int(tf[:-1] or 1)
        return n * units[tf[-1]]
    return int(tf) * 60  # plain number = minutes


def parse_body(raw: bytes | str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SignalError(f"body is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SignalError("body must be a JSON object")
    return data


def _num(d: dict, key: str, cast=float, required=True, default=None):
    if key not in d or d[key] in (None, ""):
        if required:
            raise SignalError(f"missing field {key!r}")
        return default
    try:
        return cast(d[key])
    except (TypeError, ValueError) as exc:
        raise SignalError(f"field {key!r} is not a number") from exc


def to_signal(envelope: dict[str, Any]) -> Signal:
    """Build a Signal from the alert envelope {"secret", "price", "signal": {...}}."""
    inner = envelope.get("signal")
    if not isinstance(inner, dict):
        raise SignalError("missing 'signal' object (alert message template wrong?)")

    action = str(inner.get("action", "")).lower()
    if action not in ENTRY_ACTIONS | CLOSE_ACTIONS:
        raise SignalError(f"unknown action {action!r}")

    sig = Signal(
        action=action,
        symbol=str(inner.get("symbol", "")).upper(),
        tf=str(inner.get("tf", "")),
        bar_time_ms=_num(inner, "bar_time", int),
        ref_price=_num(inner, "ref_price"),
        qty=_num(inner, "qty", int, required=action in ENTRY_ACTIONS, default=0),
        sl_dist=_num(inner, "sl_dist", required=action in ENTRY_ACTIONS, default=0.0),
        tp_dist=_num(inner, "tp_dist", required=False, default=0.0),
        fill_price=_num(envelope, "price", required=False),
        reason=str(inner.get("reason", "")),
    )
    tf_to_seconds(sig.tf)  # validates
    if sig.ref_price <= 0:
        raise SignalError("ref_price must be positive")
    if sig.is_entry:
        if sig.qty < 1:
            raise SignalError("qty must be >= 1")
        if sig.sl_dist <= 0:
            raise SignalError("entries must carry a positive sl_dist (no unprotected trades)")
    return sig
