import unittest

import numpy as np
import pandas as pd

from backtest import indicators as ind
from backtest.engine import Params, _intrabar_exit, run
from backtest.sample_data import synthetic_xauusd


class IndicatorTests(unittest.TestCase):
    def test_rma_seeded_with_sma(self):
        s = pd.Series([1.0, 2, 3, 4, 5])
        r = ind.rma(s, 3)
        self.assertTrue(np.isnan(r.iloc[1]))
        self.assertAlmostEqual(r.iloc[2], 2.0)
        self.assertAlmostEqual(r.iloc[3], 2.0 + (4 - 2.0) / 3)

    def test_adx_range(self):
        df = synthetic_xauusd(800)
        a = ind.adx(df, 14, 14).dropna()
        self.assertTrue(((a >= 0) & (a <= 100)).all())


class IntrabarTests(unittest.TestCase):
    def test_gap_through_stop_fills_at_open(self):
        self.assertEqual(_intrabar_exit(1, 95, 96, 94, stop=97, target=110), (95, "stop"))

    def test_both_hit_open_near_high_long_hits_target_first(self):
        self.assertEqual(_intrabar_exit(1, 104, 106, 90, stop=95, target=105), (105, "target"))

    def test_both_hit_open_near_low_long_hits_stop_first(self):
        self.assertEqual(_intrabar_exit(1, 96, 112, 94, stop=95, target=105), (95, "stop"))

    def test_short_target(self):
        self.assertEqual(_intrabar_exit(-1, 100, 101, 89, stop=105, target=90), (90, "target"))


class RunTests(unittest.TestCase):
    def setUp(self):
        self.df = synthetic_xauusd(3000)

    def test_run_produces_consistent_stats(self):
        res = run(self.df)
        st = res.stats
        self.assertGreater(st["trades"], 0)
        self.assertAlmostEqual(st["final_equity"], st["initial_capital"] + st["net_profit"], places=1)
        for t in res.trades:
            self.assertGreaterEqual(t.exit_time, t.entry_time)
            self.assertLessEqual(t.units, Params().max_units)

    def test_risk_per_trade_respected(self):
        res = run(self.df, Params(risk_pct=0.5))
        for t in res.trades:
            if t.exit_reason == "stop":
                # loss on a clean stop should be ~0.5% of equity (+ commission), never > 1%
                self.assertLess(-t.pnl, 0.01 * 20_000)

    def test_session_toggle_changes_behaviour(self):
        a = run(self.df, Params(use_session=True)).stats["trades"]
        b = run(self.df, Params(use_session=False)).stats["trades"]
        self.assertNotEqual(a, b)

    def test_no_trades_outside_session(self):
        res = run(self.df, Params(use_session=True, session_start_hour=8, session_end_hour=16))
        for t in res.trades:
            # entry fills on the bar after the signal, so allow hour 16
            self.assertTrue(8 <= (t.entry_time.hour - 1) % 24 < 16)


if __name__ == "__main__":
    unittest.main()
