import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from backtest.markets import default_spec, round_qty
from backtest.portfolio import PortfolioParams, run_portfolio
from backtest.sample_data import synthetic_xauusd
from bridge.brokers import PaperBroker
from bridge.config import Config
from bridge.engine import Engine
from bridge.journal import Journal
from bridge.live_strategy import PositionState, Rules, decide, trailing_stop, indicators
from bridge.news import NewsCalendar, NewsEvent
from bridge.scanner import Scanner


def trend_bars(n_up=260, n_down=40, start=1000.0, freq="1D"):
    idx = pd.date_range("2024-01-01", periods=n_up + n_down, freq=freq, tz="UTC")
    close = np.concatenate([np.linspace(start, start * 2, n_up), np.linspace(start * 2, start * 1.4, n_down)])
    open_ = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame({"open": open_, "high": np.maximum(open_, close) * 1.004,
                         "low": np.minimum(open_, close) * 0.996, "close": close}, index=idx)


class FakeFeed:
    """Serves bars up to a moving cursor, like a live feed one day at a time."""

    def __init__(self, bars: pd.DataFrame):
        self.bars = bars
        self.upto = len(bars)
        self.price = None

    def daily_bars(self, symbol):
        return self.bars.iloc[:self.upto]

    def last_price(self, symbol):
        return self.price if self.price is not None else float(self.bars.close.iloc[self.upto - 1])


class MarketsTests(unittest.TestCase):
    def test_round_qty_down(self):
        self.assertEqual(round_qty("BTCUSD", 0.123456), 0.1234)
        self.assertEqual(round_qty("XAUUSD", 2.99), 2.0)
        self.assertEqual(round_qty("EURUSD", 12999), 12000.0)

    def test_specs(self):
        self.assertFalse(default_spec("BTCUSD").allow_shorts)
        self.assertFalse(default_spec("BTCUSD").usd_news)
        self.assertTrue(default_spec("EURUSD").allow_shorts)
        with self.assertRaises(ValueError):
            default_spec("FOOBAR")


class LiveStrategyTests(unittest.TestCase):
    def test_entry_then_trail_then_exit(self):
        bars = trend_bars()
        spec = default_spec("BTCUSD")
        r = Rules()
        d = decide(bars.iloc[:250], spec, r, None)
        self.assertEqual(d.action, "buy")
        st = PositionState("BTCUSD", 1, str(bars.index[249].date()), d.ref_price - d.sl_dist, d.ref_price - d.sl_dist)
        d2 = decide(bars.iloc[:255], spec, r, st)
        self.assertEqual(d2.action, "update_stop")
        self.assertGreater(d2.stop, st.last_stop)
        st.last_stop = d2.stop
        self.assertEqual(decide(bars.iloc[:255], spec, r, st).action, "none")      # unchanged -> holding

    def test_not_enough_bars(self):
        self.assertEqual(decide(trend_bars().iloc[:50], default_spec("BTCUSD"), Rules(), None).action, "none")

    def test_news_blocks_gold_not_crypto(self):
        bars = trend_bars().iloc[:250]
        self.assertEqual(decide(bars, default_spec("XAUUSD"), Rules(), None, news_next=True).action, "none")
        self.assertEqual(decide(bars, default_spec("BTCUSD"), Rules(), None, news_next=True).action, "buy")

    def test_trailing_stop_never_loosens(self):
        bars = trend_bars()
        d = indicators(bars, Rules())
        st = PositionState("BTCUSD", 1, str(bars.index[249].date()), 1500.0, 1500.0)
        stops = [trailing_stop(d.iloc[:k], st, Rules()) for k in range(250, 300)]
        self.assertTrue(all(b >= a - 1e-9 for a, b in zip(stops, stops[1:])))


class ScannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Config(webhook_secret="s" * 24, allowed_symbols=("BTCUSD",), risk_pct=1.0,
                          max_trades_per_day=100, kill_switch_file=os.path.join(self.tmp.name, "KILL"))
        self.journal = Journal()
        self.broker = PaperBroker(25_000, spread=0.0)
        self.now = datetime(2025, 1, 1, tzinfo=timezone.utc)
        self.engine = Engine(self.cfg, self.broker, self.journal, clock=lambda: self.now)
        self.feed = FakeFeed(trend_bars())
        self.sc = Scanner(self.cfg, self.engine, {"BTCUSD": self.feed}, clock=lambda: self.now)

    def tearDown(self):
        self.journal.close()
        self.tmp.cleanup()

    def step(self, upto):
        self.feed.upto = upto
        self.now = self.feed.bars.index[upto - 1].to_pydatetime() + timedelta(days=1, minutes=5)
        return self.sc.cycle()[0]

    def test_full_lifecycle(self):
        out = self.step(250)
        self.assertIn("buy -> accepted", out)
        pos = self.broker.position("BTCUSD")
        self.assertGreater(pos.units, 0)
        self.assertEqual(round_qty("BTCUSD", pos.units), pos.units)
        first_stop = pos.stop_loss
        self.assertIn("waiting", self.sc.cycle()[0])               # same bar -> nothing new
        self.assertIn("update_stop -> accepted", self.step(255))
        self.assertGreater(self.broker.position("BTCUSD").stop_loss, first_stop)
        # walk until the position is closed by the stop or the trend exit
        closed = None
        for k in range(256, 300):
            out = self.step(k)
            if "close_long -> accepted" in out:
                closed = out
                break
        self.assertIsNotNone(closed)
        self.assertIsNone(self.broker.position("BTCUSD"))
        self.assertIsNone(self.sc._state("BTCUSD"))

    def test_paper_stop_watch_between_closes(self):
        self.step(250)
        st = self.sc._state("BTCUSD")
        self.feed.price = st.last_stop * 0.99                       # price drops through the stop intraday
        out = self.sc.cycle()[0]
        self.assertIn("close_long -> accepted", out)
        self.assertIsNone(self.broker.position("BTCUSD"))

    def test_state_survives_restart(self):
        self.step(250)
        sc2 = Scanner(self.cfg, self.engine, {"BTCUSD": self.feed}, clock=lambda: self.now)
        self.assertEqual(sc2._state("BTCUSD").side, 1)

    def test_reconcile_when_broker_closed_it(self):
        self.step(250)
        old = self.sc._state("BTCUSD")
        self.broker.close("BTCUSD", float(self.feed.bars.close.iloc[249]))
        out = self.step(251)
        new = self.sc._state("BTCUSD")
        # the stale state was dropped; the still-valid trend re-entered on the new close
        self.assertIn("buy -> accepted", out)
        self.assertNotEqual(new.signal_day, old.signal_day)

    def test_foreign_position_left_alone(self):
        self.broker.open_market("BTCUSD", 1, 0.01, 1000.0, 50.0, 0.0)
        self.assertIn("left alone", self.step(250))

    def test_one_market_error_does_not_stop_others(self):
        class Broken:
            def daily_bars(self, s): raise RuntimeError("feed down")
            def last_price(self, s): raise RuntimeError("feed down")
        self.cfg.allowed_symbols = ("ETHUSD", "BTCUSD")
        sc = Scanner(self.cfg, self.engine, {"ETHUSD": Broken(), "BTCUSD": self.feed}, clock=lambda: self.now)
        self.feed.upto = 250
        out = sc.cycle()
        self.assertIn("error: feed down", out[0])
        self.assertIn("buy -> accepted", out[1])
        self.assertIn("feed down", sc.status()["markets"]["ETHUSD"]["last_error"])

    def test_kill_switch_blocks_entries(self):
        open(self.cfg.kill_switch_file, "w").close()
        self.assertIn("rejected", self.step(250))
        self.assertIsNone(self.broker.position("BTCUSD"))

    def test_news_guard_blocks_gold_entry(self):
        self.cfg.allowed_symbols = ("XAUUSD",)
        self.engine.news = NewsCalendar([NewsEvent(datetime(2099, 1, 1, tzinfo=timezone.utc), "NFP")])
        sc = Scanner(self.cfg, self.engine, {"XAUUSD": self.feed}, clock=lambda: self.now)
        self.feed.upto = 250
        self.now = self.feed.bars.index[249].to_pydatetime() + timedelta(days=1)
        self.engine.news = NewsCalendar([NewsEvent(self.now + timedelta(hours=5), "NFP")])
        self.assertIn("news", sc.cycle()[0])


class ReplayParityTest(unittest.TestCase):
    """Replaying history through the live scanner must trade on the same days as the backtester."""

    def test_same_trade_days_as_backtest(self):
        bars = synthetic_xauusd(700, freq="1D", start_price=30000.0, seed=11)
        cfg = Config(webhook_secret="s" * 24, allowed_symbols=("BTCUSD",), risk_pct=1.0, max_trades_per_day=100,
                     max_daily_loss_pct=100, kill_switch_file="/nonexistent/KILL", news_block_hours=0)
        journal = Journal()
        broker = PaperBroker(25_000, spread=0.0)
        broker.half_spread = lambda symbol, price: 0.0      # fill exactly at the signal close, like the rules
        clock = {"now": datetime(2020, 1, 1, tzinfo=timezone.utc)}
        engine = Engine(cfg, broker, journal, clock=lambda: clock["now"])
        feed = FakeFeed(bars)
        sc = Scanner(cfg, engine, {"BTCUSD": feed}, clock=lambda: clock["now"])
        live_entries, live_exits = [], []
        for k in range(210, len(bars) + 1):
            feed.upto = k
            clock["now"] = bars.index[k - 1].to_pydatetime() + timedelta(days=1, minutes=1)
            out = sc.cycle()[0]
            day = bars.index[k - 1]
            if "close_long -> accepted" in out:
                live_exits.append(day)
            if "buy -> accepted" in out:
                live_entries.append(day)
        journal.close()

        res = run_portfolio({"BTCUSD": bars}, PortfolioParams(risk_pct=1.0, news_mode="off", max_position_lev=1.0),
                            {"BTCUSD": default_spec("BTCUSD")})
        bt = [t for t in res.trades if t.exit_reason != "end_of_data"]
        # backtest fills at the open of the bar AFTER the live signal bar
        nxt = {bars.index[i]: bars.index[i + 1] for i in range(len(bars) - 1)}
        self.assertGreater(len(bt), 3)
        self.assertEqual([nxt[d] for d in live_entries[:len(bt)]], [t.entry_time for t in bt])
        for day, t in zip(live_exits, bt):
            if t.exit_reason == "trend":
                self.assertEqual(nxt[day], t.exit_time)              # live exits at the close, backtest next open
            else:
                self.assertEqual(day, t.exit_time)                   # stop hit inside the same bar


class PortfolioTests(unittest.TestCase):
    def test_limits_respected(self):
        m = {s: synthetic_xauusd(900, freq="1D", start_price=p, seed=i)
             for i, (s, p) in enumerate((("XAUUSD", 2000.0), ("BTCUSD", 30000.0), ("ETHUSD", 2000.0)))}
        p = PortfolioParams(risk_pct=2.0, max_positions=2, max_gross_leverage=1.5, news_mode="off")
        res = run_portfolio(m, p)
        self.assertLessEqual(res.exposure["positions"].max(), 2)
        self.assertLessEqual(res.exposure["gross_leverage"].max(), 1.5 * 1.25)   # marked-to-market drift allowed
        self.assertGreater(len(res.trades), 0)

    def test_skips_markets_without_data(self):
        m = {"XAUUSD": synthetic_xauusd(600, freq="1D"), "BTCUSD": synthetic_xauusd(600, freq="1D").iloc[:0]}
        res = run_portfolio(m, PortfolioParams(news_mode="off"))
        self.assertTrue(all(t.symbol == "XAUUSD" for t in res.trades))


if __name__ == "__main__":
    unittest.main()
