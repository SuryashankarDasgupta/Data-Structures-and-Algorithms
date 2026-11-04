import json
import threading
import time
import unittest
import urllib.request

from bridge.brokers import PaperBroker
from bridge.config import Config
from bridge.engine import Engine
from bridge.journal import Journal
from bridge.worker import OrderWorker
from tests.test_bridge import BAR_1H, NOW, SECRET, close, entry, http_post, running_server


def wait_for(cond, timeout=5.0):
    """Poll until cond() is true; never sleeps longer than `timeout` in total."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


class SlowBroker(PaperBroker):
    """Paper broker whose balance/open_market take `delay` seconds and can be held on a gate."""

    def __init__(self, delay=0.0, fail_first_entry=False):
        super().__init__(10_000, spread=0.0)
        self.delay = delay
        self.gate = threading.Event()
        self.gate.set()
        self.fail_first_entry = fail_first_entry
        self.opens = 0

    def balance(self):
        time.sleep(self.delay)
        return super().balance()

    def open_market(self, *a, **kw):
        self.gate.wait(10)
        time.sleep(self.delay)
        self.opens += 1
        if self.fail_first_entry and self.opens == 1:
            raise RuntimeError("broker down")
        return super().open_market(*a, **kw)


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.cfg = Config(webhook_secret=SECRET, paper_spread=0.0, max_leverage=100.0, max_gross_leverage=100.0,
                          kill_switch_file="__no_kill_switch__")
        self.journal = Journal()
        self.workers = []

    def tearDown(self):
        for w in self.workers:
            w.stop(5)
        self.journal.close()

    def make(self, broker, **kw):
        self.broker = broker
        self.engine = Engine(self.cfg, broker, self.journal, clock=lambda: NOW)
        self.worker = OrderWorker(self.engine, **kw)
        self.workers.append(self.worker)
        return self.worker

    def submit(self, payload):
        rejected, sig = self.engine.precheck(payload)
        self.assertIsNone(rejected, rejected and rejected.detail)
        self.assertTrue(self.worker.submit(payload, sig))

    def statuses(self):
        return [r["status"] for r in self.worker.recent_results()]

    def test_slow_broker_answered_immediately(self):
        self.make(SlowBroker(delay=2.0))
        with running_server(self.engine, self.cfg, worker=self.worker) as url:
            t0 = time.monotonic()
            code, body = http_post(url, entry())
            self.assertLess(time.monotonic() - t0, 1.0)
            self.assertEqual((code, body["status"]), (202, "queued"))
            self.assertTrue(wait_for(lambda: self.broker.position("XAUUSD") is not None, 6.0))
            with urllib.request.urlopen(url + "/status", timeout=5) as resp:
                st = json.load(resp)
        self.assertEqual(st["execution_mode"], "async")
        self.assertEqual(st["recent_results"][-1]["status"], "accepted")

    def test_duplicate_while_in_flight(self):
        broker = SlowBroker()
        broker.gate.clear()                                   # hold the first order inside the broker
        self.make(broker)
        with running_server(self.engine, self.cfg, worker=self.worker) as url:
            self.assertEqual(http_post(url, entry())[0], 202)
            code, body = http_post(url, entry())
            self.assertEqual((code, body["status"]), (200, "duplicate"))
            broker.gate.set()
            self.assertTrue(wait_for(lambda: self.statuses() == ["accepted"]))
        self.assertEqual(broker.opens, 1)
        self.assertEqual(len(self.journal.orders_on(NOW.date().isoformat())), 1)

    def test_entry_then_close_in_order(self):
        self.make(SlowBroker(delay=0.2))
        self.submit(entry())
        self.submit(close(price=4020.0))
        self.assertTrue(wait_for(lambda: len(self.statuses()) == 2))
        self.assertEqual(self.statuses(), ["accepted", "accepted"])
        self.assertIsNone(self.broker.position("XAUUSD"))
        orders = self.journal.orders_on(NOW.date().isoformat())
        self.assertEqual([o["action"] for o in orders], ["open_long", "close"])
        self.assertAlmostEqual(orders[-1]["realized_pnl"], 200.0)

    def test_broker_exception_journaled_and_worker_continues(self):
        self.make(SlowBroker(fail_first_entry=True))
        self.submit(entry())
        self.submit(entry(bar=BAR_1H + 1))
        self.assertTrue(wait_for(lambda: len(self.statuses()) == 2))
        self.assertEqual(self.statuses(), ["error", "accepted"])
        self.assertTrue(self.worker.is_alive())
        rows = self.journal.signals_on(NOW.date().isoformat())
        self.assertIn("error", [r["status"] for r in rows])
        self.assertEqual(self.broker.position("XAUUSD").units, 10)

    def test_queue_full_returns_503(self):
        broker = SlowBroker()
        broker.gate.clear()
        self.make(broker, maxsize=1)
        self.submit(entry())                                  # taken by the worker, held at the gate
        self.assertTrue(wait_for(lambda: self.worker.depth() == 0))
        self.submit(close(bar=BAR_1H + 1))                    # fills the one queue slot
        with running_server(self.engine, self.cfg, worker=self.worker) as url:
            code, body = http_post(url, entry(bar=BAR_1H + 2))
        self.assertEqual((code, body["detail"]), (503, "order queue full"))
        rejected, _ = self.engine.precheck(entry(bar=BAR_1H + 2))   # key was released, not stuck in flight
        self.assertIsNone(rejected)
        broker.gate.set()

    def test_stop_drains_pending(self):
        broker = SlowBroker()
        broker.gate.clear()
        self.make(broker)
        self.submit(entry())
        self.submit(close(price=4010.0, bar=BAR_1H + 1))
        self.submit(entry(bar=BAR_1H + 2))
        broker.gate.set()
        self.assertTrue(self.worker.stop(5))
        self.assertEqual(len(self.statuses()), 3)
        self.assertFalse(self.worker.is_alive())

    def test_sync_mode_status(self):
        self.make(PaperBroker(10_000, spread=0.0))
        with running_server(self.engine, self.cfg) as url:
            self.assertEqual(http_post(url, entry())[1]["status"], "accepted")
            with urllib.request.urlopen(url + "/status", timeout=5) as resp:
                st = json.load(resp)
        self.assertEqual((st["execution_mode"], st["queue_depth"], st["recent_results"]), ("sync", 0, []))


class ExecutionModeConfigTests(unittest.TestCase):
    def test_auto_mode(self):
        self.assertEqual(Config(broker="paper").resolved_execution_mode(), "sync")
        self.assertEqual(Config(broker="oanda").resolved_execution_mode(), "async")
        self.assertEqual(Config(broker="paper", execution_mode="async").resolved_execution_mode(), "async")

    def test_bad_mode_refused(self):
        with self.assertRaises(ValueError):
            Config(webhook_secret=SECRET, execution_mode="fast").validate()


if __name__ == "__main__":
    unittest.main()
