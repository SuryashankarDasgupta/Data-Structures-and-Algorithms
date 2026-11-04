import csv
import os
import re
import tempfile
import unittest
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

from backtest.engine import Params, event_ahead, run
from backtest.news import load_events
from backtest.sample_data import synthetic_xauusd
from bridge.config import Config
from bridge.engine import Engine
from bridge.journal import Journal
from bridge.news import NewsCalendar, NewsEvent, _event_time, merge_rows, parse_forexfactory, sync_pine
from bridge.brokers import PaperBroker

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class CalendarDataTests(unittest.TestCase):
    def test_bundled_calendar_sane(self):
        with open(os.path.join(HERE, "data", "high_impact_usd.csv")) as fh:
            rows = list(csv.DictReader(fh))
        for kind in ("NFP", "CPI"):
            ds = [date.fromisoformat(r["date"]) for r in rows if r["event"] == kind]
            self.assertGreaterEqual(len(ds), 130)
            self.assertTrue(all(d.weekday() < 5 for d in ds), f"{kind} on a weekend")
            years = pd.Series([d.year for d in ds]).value_counts()
            self.assertTrue((years.loc[2016:2024] == 12).all(), f"{kind} not monthly")
        fomc = [date.fromisoformat(r["date"]) for r in rows if r["event"] == "FOMC"]
        self.assertIn(date(2020, 3, 15), fomc)          # emergency cut
        self.assertTrue(all(c == 8 for y, c in pd.Series([d.year for d in fomc]).value_counts().items()
                            if y not in (2020,)))

    def test_pine_calendar_matches_csv(self):
        with open(os.path.join(HERE, "pine", "xauusd_daily_trend.pine")) as fh:
            src = fh.read()
        with open(os.path.join(HERE, "data", "high_impact_usd.csv")) as fh:
            rows = list(csv.DictReader(fh))
        for kind in ("FOMC", "NFP", "CPI"):
            m = re.search(rf'^{kind}_DATES\s*=\s*"([0-9,]*)"$', src, re.M)
            self.assertIsNotNone(m)
            pine = set(m.group(1).split(","))
            csvd = {r["date"].replace("-", "") for r in rows if r["event"] == kind}
            self.assertEqual(pine, csvd, f"{kind}: run `python -m bridge.news pine`")


class EventAheadTests(unittest.TestCase):
    def idx(self, *days):
        return pd.DatetimeIndex([pd.Timestamp(d, tz="UTC") for d in days])

    def test_next_session(self):
        ix = self.idx("2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09")  # Tue..Fri
        self.assertEqual(list(event_ahead(ix, [date(2026, 1, 9)])), [False, False, True, False])

    def test_friday_sees_weekend_and_monday(self):
        ix = self.idx("2020-03-13", "2020-03-16")
        self.assertTrue(event_ahead(ix, [date(2020, 3, 15)])[0])      # Sunday emergency cut
        self.assertTrue(event_ahead(ix, [date(2020, 3, 16)])[0])

    def test_last_bar_looks_one_weekday_ahead(self):
        ix = self.idx("2026-11-04", "2026-11-05")
        self.assertTrue(event_ahead(ix, [date(2026, 11, 6)])[-1])

    def test_no_events(self):
        self.assertFalse(event_ahead(self.idx("2026-01-06"), []).any())


class BacktestNewsModeTests(unittest.TestCase):
    def setUp(self):
        self.df = synthetic_xauusd(1500, freq="1D")
        days = self.df.index.tz_convert(None).normalize()
        self.events = [d.date() for d in days[300::7]]             # an event every ~week
        self.ev_set = set(self.events)

    def test_block_no_fills_on_event_days(self):
        res = run(self.df, Params(news_mode="block"), events=self.events)
        for t in res.trades:
            self.assertNotIn(t.entry_time.date(), self.ev_set)

    def test_off_ignores_news(self):
        a = run(self.df, Params(news_mode="off"), events=self.events)
        self.assertTrue(any(t.entry_time.date() in self.ev_set for t in a.trades))

    def test_flat_exits_before_news(self):
        res = run(self.df, Params(news_mode="flat"), events=self.events)
        news_exits = [t for t in res.trades if t.exit_reason == "news"]
        self.assertTrue(news_exits)
        for t in news_exits:
            self.assertIn(t.exit_time.date(), self.ev_set)        # exited at the event-day open

    def test_tighten_raises_stops(self):
        base = run(self.df, Params(news_mode="block"), events=self.events)
        tight = run(self.df, Params(news_mode="tighten", news_tighten_atr=0.5), events=self.events)
        self.assertGreaterEqual(len(tight.trades), len(base.trades))

    def test_bad_mode(self):
        with self.assertRaises(ValueError):
            run(self.df, Params(news_mode="maybe"), events=[])

    def test_default_loads_bundled_calendar(self):
        self.assertGreater(len(load_events()), 300)


class BridgeNewsTests(unittest.TestCase):
    def test_ny_time_with_dst(self):
        self.assertEqual(_event_time(date(2026, 7, 2), "NFP"), datetime(2026, 7, 2, 12, 30, tzinfo=timezone.utc))
        self.assertEqual(_event_time(date(2026, 12, 4), "NFP"), datetime(2026, 12, 4, 13, 30, tzinfo=timezone.utc))
        self.assertEqual(_event_time(date(2026, 12, 9), "FOMC"), datetime(2026, 12, 9, 19, 0, tzinfo=timezone.utc))
        self.assertEqual(_event_time(date(2026, 12, 9), "FOMC", "18:30"), datetime(2026, 12, 9, 18, 30, tzinfo=timezone.utc))

    def test_upcoming_window(self):
        e = NewsEvent(datetime(2026, 11, 6, 13, 30, tzinfo=timezone.utc), "NFP")
        cal = NewsCalendar([e])
        self.assertEqual(cal.upcoming(datetime(2026, 11, 5, 14, 0, tzinfo=timezone.utc), 24), [e])
        self.assertEqual(cal.upcoming(datetime(2026, 11, 5, 13, 0, tzinfo=timezone.utc), 24), [])
        self.assertEqual(cal.upcoming(datetime(2026, 11, 6, 13, 50, tzinfo=timezone.utc), 24, 30), [e])
        self.assertTrue(cal.is_stale(datetime(2026, 12, 1, tzinfo=timezone.utc)))
        self.assertFalse(cal.is_stale(datetime(2026, 11, 1, tzinfo=timezone.utc)))

    def test_engine_rejects_entry_before_news_but_allows_close(self):
        now = datetime(2026, 11, 5, 22, 0, 5, tzinfo=timezone.utc)
        bar = int(datetime(2026, 11, 4, 22, 0, tzinfo=timezone.utc).timestamp() * 1000)
        cfg = Config(webhook_secret="s" * 24, paper_spread=0.0, max_leverage=100)
        cal = NewsCalendar([NewsEvent(datetime(2026, 11, 6, 13, 30, tzinfo=timezone.utc), "NFP")])
        broker = PaperBroker(25_000, spread=0.0)
        broker.open_market("XAUUSD", 1, 2, 4000.0, 100.0, 0.0)
        j = Journal()
        eng = Engine(cfg, broker, j, clock=lambda: now, news=cal)
        close = {"secret": cfg.webhook_secret, "price": 4010,
                 "signal": {"action": "close_long", "symbol": "XAUUSD", "ref_price": 4010, "tf": "D", "bar_time": bar}}
        entry = {"secret": cfg.webhook_secret, "price": 4010,
                 "signal": {"action": "buy", "symbol": "XAUUSD", "qty": 2, "ref_price": 4010, "sl_dist": 100,
                            "tp_dist": 0, "tf": "D", "bar_time": bar + 1}}
        self.assertEqual(eng.handle(close).status, "accepted")
        r = eng.handle(entry)
        self.assertEqual(r.status, "rejected")
        self.assertIn("NFP 2026-11-06 13:30 UTC", r.detail)
        cfg.news_block_hours = 0                                      # guard off -> allowed
        entry["signal"]["bar_time"] = bar + 2
        self.assertEqual(eng.handle(entry).status, "accepted")
        j.close()

    def test_forexfactory_parse_and_merge(self):
        items = [
            {"title": "Non-Farm Employment Change", "country": "USD", "date": "2026-12-04T08:30:00-05:00", "impact": "High"},
            {"title": "CPI m/m", "country": "USD", "date": "2026-12-10T08:30:00-05:00", "impact": "High"},
            {"title": "Federal Funds Rate", "country": "USD", "date": "2026-12-09T14:00:00-05:00", "impact": "High"},
            {"title": "CPI m/m", "country": "EUR", "date": "2026-12-10T05:00:00-05:00", "impact": "High"},
            {"title": "Unemployment Claims", "country": "USD", "date": "2026-12-03T08:30:00-05:00", "impact": "Medium"},
        ]
        rows = parse_forexfactory(items)
        self.assertEqual(rows, [("2026-12-04", "NFP", "Non-Farm Employment Change (ForexFactory)", "13:30"),
                                ("2026-12-10", "CPI", "CPI m/m (ForexFactory)", "13:30"),
                                ("2026-12-09", "FOMC", "Federal Funds Rate (ForexFactory)", "19:00")])
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cal.csv")
            with open(path, "w") as fh:
                fh.write("date,event,description\n2026-12-09,FOMC,FOMC rate decision\n")
            self.assertEqual(merge_rows(path, rows), 2)              # FOMC already present
            self.assertEqual(merge_rows(path, rows), 0)              # idempotent
            cal = NewsCalendar.load(path)
            self.assertEqual(len(cal.events), 3)

    def test_merge_rows_writes_lf_line_endings(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "cal.csv")
            with open(path, "w", newline="") as fh:
                fh.write("date,event,description\n2026-12-09,FOMC,FOMC rate decision\n")
            self.assertEqual(merge_rows(path, [("2026-12-04", "NFP", "x", "13:30")]), 1)
            with open(path, "rb") as fh:
                raw = fh.read()
            self.assertNotIn(b"\r", raw)
            self.assertEqual(raw.count(b"\n"), 3)

    def test_sync_pine(self):
        with tempfile.TemporaryDirectory() as d:
            csvp, pinep = os.path.join(d, "c.csv"), os.path.join(d, "s.pine")
            with open(csvp, "w") as fh:
                fh.write("date,event,description\n2026-01-09,NFP,x\n2026-01-13,CPI,y\n2026-01-28,FOMC,z\n")
            with open(pinep, "w") as fh:
                fh.write('a\nFOMC_DATES = "1"\nNFP_DATES  = ""\nCPI_DATES  = "2,3"\nb\n')
            sync_pine(csvp, pinep)
            with open(pinep) as fh:
                out = fh.read()
            self.assertIn('FOMC_DATES = "20260128"', out)
            self.assertIn('NFP_DATES  = "20260109"', out)
            self.assertIn('CPI_DATES  = "20260113"', out)


if __name__ == "__main__":
    unittest.main()
