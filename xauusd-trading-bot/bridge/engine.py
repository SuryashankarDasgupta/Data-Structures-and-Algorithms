"""Core alert-handling pipeline: authenticate -> validate -> dedupe -> risk -> execute -> journal."""
from __future__ import annotations

import hmac
import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from .brokers import Broker
from .journal import Journal
from .risk import RiskManager
from .signals import Signal, SignalError, parse_body, tf_to_seconds, to_signal

log = logging.getLogger(__name__)


@dataclass
class Result:
    http_status: int
    status: str          # accepted | rejected | duplicate | error | ignored
    detail: str = ""

    def as_dict(self) -> dict:
        return {"status": self.status, "detail": self.detail}


class Engine:
    def __init__(self, cfg, broker: Broker, journal: Journal,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc), news=None):
        self.cfg = cfg
        self.broker = broker
        self.journal = journal
        self.news = news
        self.risk = RiskManager(cfg, journal, news)
        self.clock = clock
        self._lock = threading.Lock()   # one order at a time: single writer to the broker

    # ------------------------------------------------------------------
    def handle_raw(self, raw: bytes | str) -> Result:
        try:
            envelope = parse_body(raw)
        except SignalError as exc:
            self.journal.log_signal("rejected", str(exc), raw if isinstance(raw, str) else raw.decode(errors="replace"))
            return Result(400, "rejected", str(exc))
        return self.handle(envelope)

    def handle(self, envelope: dict[str, Any]) -> Result:
        secret = str(envelope.get("secret", ""))
        if not hmac.compare_digest(secret.encode(), self.cfg.webhook_secret.encode()):
            self.journal.log_signal("rejected", "bad secret", envelope)
            return Result(401, "rejected", "unauthorized")

        try:
            sig = to_signal(envelope)
        except SignalError as exc:
            self.journal.log_signal("rejected", str(exc), envelope)
            return Result(400, "rejected", str(exc))

        if sig.symbol not in self.cfg.allowed_symbols:
            return self._reject(envelope, sig, f"symbol {sig.symbol} not allowed")

        now = self.clock()
        bar_close = sig.bar_time_ms / 1000 + tf_to_seconds(sig.tf)
        age = now.timestamp() - bar_close
        if age > self.cfg.max_signal_delay_s:
            return self._reject(envelope, sig, f"stale signal ({age:.0f}s after bar close)")

        with self._lock:
            if self.journal.is_duplicate(sig.dedupe_key):
                self.journal.log_signal("duplicate", "already processed", envelope, sig.dedupe_key, sig.action)
                return Result(200, "duplicate", "already processed")
            try:
                if sig.is_entry:
                    return self._entry(envelope, sig, now)
                if sig.action == "update_stop":
                    return self._update_stop(envelope, sig)
                return self._close(envelope, sig, now)
            except Exception as exc:  # noqa: BLE001 - never crash the server on broker errors
                log.exception("broker error")
                self.journal.log_signal("error", f"broker error: {exc}", envelope, sig.dedupe_key, sig.action)
                return Result(502, "error", f"broker error: {exc}")

    # ------------------------------------------------------------------
    def _reject(self, envelope, sig: Signal, reason: str) -> Result:
        self.journal.log_signal("rejected", reason, envelope, sig.dedupe_key, sig.action)
        log.info("rejected %s: %s", sig.dedupe_key, reason)
        return Result(200, "rejected", reason)   # 200 so TradingView doesn't treat it as a delivery failure

    def _entry(self, envelope, sig: Signal, now: datetime) -> Result:
        balance = self.broker.balance()
        pos = self.broker.position(sig.symbol)
        decision = self.risk.check_entry(sig, balance, pos is not None, now)
        if not decision.allowed:
            return self._reject(envelope, sig, decision.reason)

        fill = self.broker.open_market(sig.symbol, sig.side, decision.units, sig.ref_price,
                                       sig.sl_dist, sig.tp_dist)
        action = "open_long" if sig.side > 0 else "open_short"
        sl = tp = None
        if fill.price is not None:
            sl = round(fill.price - sig.side * sig.sl_dist, 3)
            tp = round(fill.price + sig.side * sig.tp_dist, 3) if sig.tp_dist else None
        self.journal.log_order(sig.symbol, action, fill.units or sig.side * decision.units, fill.price,
                               fill.status, sl, tp, broker_ref=fill.broker_ref, now=now)
        if fill.status == "failed":
            self.journal.log_signal("error", f"order failed: {fill.message}", envelope, None, sig.action)
            return Result(200, "error", f"order failed: {fill.message}")
        detail = f"{action} {abs(fill.units)} oz @ {fill.price} SL {sl} TP {tp}"
        if decision.reason:
            detail += f" ({decision.reason})"
        if fill.status == "unknown":
            detail += f" [UNVERIFIED: {fill.message}]"
        self.journal.log_signal("accepted", detail, envelope, sig.dedupe_key, sig.action)
        log.info(detail)
        return Result(200, "accepted", detail)

    def _update_stop(self, envelope, sig: Signal) -> Result:
        pos = self.broker.position(sig.symbol)
        if pos is None:
            self.journal.log_signal("accepted", "no position for stop update", envelope, sig.dedupe_key, sig.action)
            return Result(200, "ignored", "no open position")
        # a stop on the wrong side of the market would close immediately; refuse it
        if (pos.units > 0 and sig.stop >= sig.ref_price) or (pos.units < 0 and sig.stop <= sig.ref_price):
            return self._reject(envelope, sig, f"stop {sig.stop} is on the wrong side of price {sig.ref_price}")
        fill = self.broker.update_stop(sig.symbol, sig.stop)
        if fill.status != "filled":
            return self._reject(envelope, sig, f"stop not moved: {fill.message}")
        detail = f"stop moved to {sig.stop}"
        self.journal.log_signal("accepted", detail, envelope, sig.dedupe_key, sig.action)
        log.info(detail)
        return Result(200, "accepted", detail)

    def _close(self, envelope, sig: Signal, now: datetime) -> Result:
        pos = self.broker.position(sig.symbol)
        wanted = {"close_long": lambda p: p.units > 0,
                  "close_short": lambda p: p.units < 0,
                  "close_all": lambda p: True}[sig.action]
        if pos is None or not wanted(pos):
            # e.g. the broker's own SL/TP already closed it. Nothing to do.
            self.journal.log_signal("accepted", "no matching position (already flat)", envelope,
                                    sig.dedupe_key, sig.action)
            return Result(200, "ignored", "no matching position")

        price_hint: Optional[float] = sig.fill_price if sig.fill_price else sig.ref_price
        fill = self.broker.close(sig.symbol, price_hint)
        self.journal.log_order(sig.symbol, "close", fill.units, fill.price, fill.status,
                               realized_pnl=fill.realized_pnl, broker_ref=fill.broker_ref, now=now)
        if fill.status != "filled":
            self.journal.log_signal("error", f"close failed: {fill.message}", envelope, None, sig.action)
            return Result(200, "error", f"close failed: {fill.message}")
        detail = f"closed {abs(fill.units)} oz @ {fill.price} pnl {fill.realized_pnl} ({sig.reason})"
        self.journal.log_signal("accepted", detail, envelope, sig.dedupe_key, sig.action)
        log.info(detail)
        return Result(200, "accepted", detail)
