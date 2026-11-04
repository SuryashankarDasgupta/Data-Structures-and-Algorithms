"""24/7 multi-market scanner.

Every SCAN_INTERVAL_S seconds (default 300) it checks every market in ALLOWED_SYMBOLS:
  1. reconcile: a position the broker closed (e.g. its stop was hit) is forgotten
  2. paper broker only: the latest price is checked against the stop and the position is closed if breached
     (a real broker holds the stop itself)
  3. when a new daily bar has completed, the trend rules decide: enter, trail the stop, or exit

Orders go through Engine.submit_internal, so every risk limit, duplicate check and journal entry that applies
to TradingView webhooks applies here too. Position state (signal day, initial and last stop) is stored in the
journal, and the trailing stop is recomputed from the bars, so restarts are safe.

The strategy trades daily bars: checking more often does not mean trading more often. It means stops and
new daily closes are acted on within minutes, around the clock (crypto trades 24/7; gold/forex 24/5).

    python -m bridge.scanner --once        # run one cycle and exit (uses .env / environment settings)
"""
from __future__ import annotations

import argparse
import json
import logging
import threading
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

import pandas as pd

from backtest.markets import default_spec, round_qty

from .brokers import PaperBroker
from .engine import Engine
from .live_strategy import Decision, PositionState, Rules, decide
from .signals import Signal

log = logging.getLogger(__name__)


def _ms(ts) -> int:
    return int(pd.Timestamp(ts).timestamp() * 1000)


class Scanner:
    def __init__(self, cfg, engine: Engine, feeds: dict, rules: Optional[Rules] = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.cfg = cfg
        self.engine = engine
        self.feeds = feeds
        self.rules = rules or Rules()
        self.clock = clock
        self.journal = engine.journal
        self._stop = threading.Event()

    # ---------------- state ----------------
    def _state(self, sym: str) -> Optional[PositionState]:
        raw = self.journal.get(f"scanner:pos:{sym}")
        return PositionState(**json.loads(raw)) if raw else None

    def _save(self, st: Optional[PositionState], sym: str) -> None:
        self.journal.set(f"scanner:pos:{sym}", json.dumps(asdict(st)) if st else "")

    def status(self) -> dict:
        out = {"last_cycle": self.journal.get("scanner:last_cycle"), "markets": {}}
        for s in self.cfg.allowed_symbols:
            st = self._state(s)
            out["markets"][s] = {"last_bar": self.journal.get(f"scanner:last_bar:{s}"),
                                 "position": asdict(st) if st else None,
                                 "last_error": self.journal.get(f"scanner:error:{s}") or None}
        return out

    @staticmethod
    def _effective_stop(st: Optional[PositionState], pos) -> float:
        """Tighter of the strategy's trailing stop and the broker's stop (set from the actual fill price)."""
        if st is None:
            return float("nan")
        broker = getattr(pos, "stop_loss", None) if pos is not None else None
        if broker is None:
            return st.last_stop
        return max(st.last_stop, broker) if st.side > 0 else min(st.last_stop, broker)

    # ---------------- loop ----------------
    def run_forever(self) -> None:
        log.info("scanner started: %s every %ss", ",".join(self.cfg.allowed_symbols), self.cfg.scan_interval_s)
        while not self._stop.is_set():
            self.cycle()
            self._stop.wait(self.cfg.scan_interval_s)

    def stop(self) -> None:
        self._stop.set()

    def cycle(self) -> list[str]:
        notes = []
        for sym in self.cfg.allowed_symbols:
            try:
                note = self.scan_symbol(sym)
                self.journal.set(f"scanner:error:{sym}", "")
            except Exception as exc:  # noqa: BLE001 - one market's failure must not stop the others
                log.exception("scan %s failed", sym)
                note = f"error: {exc}"
                self.journal.set(f"scanner:error:{sym}", f"{self.clock().isoformat()} {exc}")
            notes.append(f"{sym}: {note}")
        self.journal.set("scanner:last_cycle", self.clock().isoformat())
        return notes

    # ---------------- per market ----------------
    def _news_next(self, now: datetime) -> bool:
        news = self.engine.news
        return bool(news and self.cfg.news_block_hours > 0 and news.upcoming(now, self.cfg.news_block_hours))

    def _submit(self, sym: str, action: str, bar_ts, ref: float, **kw) -> str:
        sig = Signal(action=action, symbol=sym, tf="D", bar_time_ms=_ms(bar_ts), ref_price=ref, **kw)
        res = self.engine.submit_internal(sig)
        return f"{action} -> {res.status}: {res.detail}"

    def scan_symbol(self, sym: str) -> str:
        feed = self.feeds[sym]
        now = self.clock()
        spec = default_spec(sym, self.cfg.fx_shorts, self.cfg.crypto_shorts)
        st = self._state(sym)
        pos = self.engine.broker.position(sym)

        if st and pos is None:                       # closed elsewhere (broker stop, manual close)
            self._save(None, sym)
            st = None
        if pos is not None and st is None:
            return "position not opened by the scanner: left alone"

        paper = isinstance(self.engine.broker, PaperBroker)
        stop_now = self._effective_stop(st, pos)
        if st and paper:                             # simulate the broker-side stop between daily closes
            px = feed.last_price(sym)
            if (st.side > 0 and px <= stop_now) or (st.side < 0 and px >= stop_now):
                out = self._submit(sym, "close_long" if st.side > 0 else "close_short", now, px,
                                   fill_price=px, reason="stop")
                self._save(None, sym)
                return out

        bars = feed.daily_bars(sym)
        if bars.empty:
            return "no data"
        bar_ts = bars.index[-1]
        bar_day = pd.Timestamp(bar_ts).tz_convert(None).date().isoformat()
        if self.journal.get(f"scanner:last_bar:{sym}") == bar_day:
            return f"waiting for the next daily close (last {bar_day})"

        prefix = ""
        if st and paper:                             # a stop breached inside the bar we hadn't seen yet
            last = bars.iloc[-1]
            if bar_day > st.signal_day and (
                    (st.side > 0 and last.low <= stop_now) or (st.side < 0 and last.high >= stop_now)):
                fill = min(stop_now, last.open) if st.side > 0 else max(stop_now, last.open)
                prefix = self._submit(sym, "close_long" if st.side > 0 else "close_short", bar_ts, fill,
                                      fill_price=fill, reason="stop") + "; "
                self._save(None, sym)
                st = None                            # like the backtest, this close may re-enter at once

        d: Decision = decide(bars, spec, self.rules, st, self._news_next(now))
        out = f"{bar_day}: {d.action} ({d.reason})"
        if d.action in ("buy", "sell"):
            side = 1 if d.action == "buy" else -1
            equity = self.engine.broker.balance()
            qty = min(equity * self.cfg.risk_pct / 100 / d.sl_dist, equity * self.cfg.max_leverage / d.ref_price)
            qty = round_qty(sym, qty)
            if qty <= 0:
                out += " skipped: account too small for the minimum order"
            else:
                out = self._submit(sym, d.action, bar_ts, d.ref_price, qty=qty, sl_dist=d.sl_dist, reason=d.reason)
                if "-> accepted" in out:
                    stop = d.ref_price - side * d.sl_dist
                    self._save(PositionState(sym, side, bar_day, stop, stop), sym)
        elif d.action == "update_stop" and st:
            out = self._submit(sym, "update_stop", bar_ts, d.ref_price, stop=d.stop, reason=d.reason)
            # The strategy's stop advances even if the broker refused (its own stop, set from the actual fill,
            # can already be tighter). The effective stop is always the tighter of the two.
            st.last_stop = d.stop
            self._save(st, sym)
        elif d.action == "close" and st:
            out = self._submit(sym, "close_long" if st.side > 0 else "close_short", bar_ts, d.ref_price,
                               fill_price=None if not paper else feed.last_price(sym), reason=d.reason)
            if "-> accepted" in out or "-> ignored" in out:
                self._save(None, sym)
        self.journal.set(f"scanner:last_bar:{sym}", bar_day)
        return prefix + out


def main(argv=None) -> None:
    from .brokers import make_broker
    from .config import Config
    from .feeds import make_feeds
    from .journal import Journal
    from .news import DEFAULT_PATH, NewsCalendar
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--once", action="store_true", help="run a single cycle and print what happened")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = Config.from_env()
    cfg.validate()
    news = NewsCalendar.load(cfg.news_calendar or DEFAULT_PATH, cfg.news_events) if cfg.news_block_hours > 0 else None
    engine = Engine(cfg, make_broker(cfg), Journal(cfg.journal_path), news=news)
    sc = Scanner(cfg, engine, make_feeds(cfg))
    if args.once:
        for line in sc.cycle():
            print(line)
        return
    try:
        sc.run_forever()
    except KeyboardInterrupt:
        sc.stop()


if __name__ == "__main__":
    main()
