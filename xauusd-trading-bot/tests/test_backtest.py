import unittest

import numpy as np
import pandas as pd

from backtest import indicators as ind
from backtest.engine import Params, _stop_fill, rebase, run
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


class StopFillTests(unittest.TestCase):
    def test_long_gap_through_stop_fills_at_open(self):
        self.assertEqual(_stop_fill(1, 95, 96, 94, 97), 95)

    def test_long_touch_fills_at_stop(self):
        self.assertEqual(_stop_fill(1, 100, 101, 96, 97), 97)

    def test_long_not_hit(self):
        self.assertIsNone(_stop_fill(1, 100, 101, 98, 97))

    def test_short(self):
        self.assertEqual(_stop_fill(-1, 100, 104, 99, 103), 103)
        self.assertEqual(_stop_fill(-1, 105, 106, 104, 103), 105)


def trend_then_crash(n_up=400, n_down=60):
    """Deterministic series: steady uptrend then a sharp fall."""
    idx = pd.date_range("2020-01-01", periods=n_up + n_down, freq="1D", tz="UTC")
    close = np.concatenate([np.linspace(1000, 2000, n_up), np.linspace(2000, 1400, n_down)])
    open_ = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame({"open": open_, "high": np.maximum(open_, close) + 5,
                         "low": np.minimum(open_, close) - 5, "close": close}, index=idx)


class RunTests(unittest.TestCase):
    def setUp(self):
        self.df = synthetic_xauusd(3000, freq="1D")

    def test_stats_consistent(self):
        res = run(self.df)
        st = res.stats
        self.assertGreater(st["trades"], 0)
        self.assertAlmostEqual(st["final_equity"], st["initial_capital"] + st["net_profit"], places=1)
        for t in res.trades:
            self.assertGreaterEqual(t.exit_time, t.entry_time)

    def test_rebased_stats_consistent(self):
        res = run(self.df)
        start = res.equity.index[len(res.equity) // 2]
        st = rebase(res, start).stats
        self.assertEqual(st["start"], str(start.date()))
        self.assertAlmostEqual(res.equity.iloc[0], st["initial_capital"])
        self.assertAlmostEqual(st["final_equity"], st["initial_capital"] + st["net_profit"], places=1)
        self.assertAlmostEqual(st["return_pct"], st["net_profit"] / st["initial_capital"] * 100, places=1)
        self.assertTrue(all(t.entry_time >= start for t in res.trades))

    def test_fresh_start_account(self):
        start = self.df.index[len(self.df) // 2]
        res = run(self.df, trade_from=start)
        self.assertTrue(res.trades)
        self.assertTrue(all(t.entry_time > start for t in res.trades))
        self.assertTrue((res.equity.loc[:start] == res.params.initial_capital).all())
        st = rebase(res, start).stats
        self.assertEqual(res.equity.iloc[0], st["initial_capital"])
        self.assertAlmostEqual(st["final_equity"], st["initial_capital"] + st["net_profit"], places=1)

    def test_long_only_by_default(self):
        self.assertTrue(all(t.side == 1 for t in run(self.df).trades))
        self.assertTrue(any(t.side == -1 for t in run(self.df, Params(allow_shorts=True)).trades))

    def test_trailing_stop_never_loosens(self):
        res = run(self.df)
        s = res.stops
        for t in res.trades:
            seg = s.loc[t.entry_time:t.exit_time].dropna()
            self.assertTrue((seg.diff().dropna() >= -1e-9).all())

    def test_quantity_step_and_leverage_cap(self):
        p = Params(qty_step=1.0, max_lev=0.5, risk_pct=3.0)
        res = run(self.df, p)
        for t in res.trades:
            self.assertEqual(t.units, int(t.units))
            # notional at entry can't exceed 0.5x equity by more than one bar's gap
            self.assertLess(t.units * t.entry_price, 0.6 * res.equity.max())

    def test_uptrend_captured_and_crash_exited(self):
        res = run(trend_then_crash(), Params(slow_len=100, initial_capital=100_000))
        self.assertGreater(res.stats["net_profit"], 0)
        last = res.trades[-1]
        self.assertNotEqual(last.exit_reason, "end_of_data")   # stop got us out of the crash
        self.assertGreater(last.exit_price, 1400)

    def test_risk_per_trade_respected(self):
        res = run(self.df)                                   # default 2% risk
        for t in res.trades:
            if t.exit_reason == "initial_stop":
                # loss on a clean stop ~= 2% of equity (+ commission, gaps)
                self.assertLess(-t.pnl, 0.035 * res.equity.max())


if __name__ == "__main__":
    unittest.main()


class PeriodStatsTests(unittest.TestCase):
    def test_flat_and_rising(self):
        from backtest.engine import period_stats
        idx = pd.date_range("2024-01-01", periods=60, freq="1D", tz="UTC")
        flat = period_stats(pd.Series(100.0, index=idx))
        self.assertEqual(flat.loc["flat_pct", "daily"], 100.0)
        rising = period_stats(pd.Series(np.linspace(100, 160, 60), index=idx))
        self.assertEqual(rising.loc["losing_pct", "monthly"], 0.0)
        self.assertEqual(rising.loc["worst_drawdown_pct", "weekly"], 0.0)

    def test_drawdown_inside_period(self):
        from backtest.engine import period_stats
        idx = pd.date_range("2024-01-01", periods=4, freq="1D", tz="UTC")
        st = period_stats(pd.Series([100.0, 110.0, 99.0, 105.0], index=idx))
        self.assertAlmostEqual(st.loc["worst_drawdown_pct", "monthly"], -10.0)   # 110 -> 99
        self.assertAlmostEqual(st.loc["best_pct", "monthly"], 5.0)
