import contextlib
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer

from bridge.brokers import OandaBroker, PaperBroker
from bridge.config import LIVE_CONFIRMATION, Config
from bridge.engine import Engine
from bridge.journal import Journal
from bridge.report import build_report
from bridge.server import make_handler
from bridge.signals import SignalError, tf_to_seconds, to_signal

SECRET = "s" * 24
NOW = datetime(2026, 11, 4, 14, 0, 5, tzinfo=timezone.utc)
BAR_1H = int(datetime(2026, 11, 4, 13, 0, tzinfo=timezone.utc).timestamp() * 1000)  # closes 14:00


def entry(action="buy", qty=10, sl=10.0, tp=20.0, bar=BAR_1H, price=4000.0, secret=SECRET):
    return {"secret": secret, "price": price,
            "signal": {"action": action, "symbol": "XAUUSD", "qty": qty, "ref_price": price,
                       "sl_dist": sl, "tp_dist": tp, "tf": "60", "bar_time": bar}}


def close(action="close_long", price=4020.0, bar=BAR_1H, reason="sl_tp"):
    return {"secret": SECRET, "price": price,
            "signal": {"action": action, "symbol": "XAUUSD", "reason": reason,
                       "ref_price": price, "tf": "60", "bar_time": bar}}


def stop_update(stop, ref=4002.0, bar=BAR_1H):
    return {"secret": SECRET,
            "signal": {"action": "update_stop", "symbol": "XAUUSD", "stop": stop,
                       "ref_price": ref, "tf": "60", "bar_time": bar}}


@contextlib.contextmanager
def running_server(engine, cfg, **kw):
    """Real bridge HTTP server on 127.0.0.1 with an ephemeral port; yields its base URL."""
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(engine, cfg, **kw))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


def http_post(url, payload, headers=None):
    """POST JSON; returns (status code, parsed body) for any status, 4xx/5xx included."""
    req = urllib.request.Request(url + "/webhook", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as err:
        return err.code, json.load(err)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = Config(webhook_secret=SECRET, paper_spread=0.0, max_leverage=100.0, max_gross_leverage=100.0,
                          kill_switch_file=os.path.join(self.tmp.name, "KILL"))
        self.broker = PaperBroker(10_000, spread=0.0)
        self.journal = Journal()
        self.engine = Engine(self.cfg, self.broker, self.journal, clock=lambda: NOW)

    def tearDown(self):
        self.journal.close()
        self.tmp.cleanup()


class SignalTests(unittest.TestCase):
    def test_tf(self):
        self.assertEqual(tf_to_seconds("60"), 3600)
        self.assertEqual(tf_to_seconds("15"), 900)
        self.assertEqual(tf_to_seconds("D"), 86400)
        self.assertEqual(tf_to_seconds("4H".replace("H", "S")), 4)

    def test_entry_requires_stop(self):
        with self.assertRaises(SignalError):
            to_signal(entry(sl=0))

    def test_unknown_action(self):
        bad = entry()
        bad["signal"]["action"] = "yolo"
        with self.assertRaises(SignalError):
            to_signal(bad)

    def test_missing_signal_object(self):
        with self.assertRaises(SignalError):
            to_signal({"secret": SECRET, "price": 1})


class EngineTests(Base):
    def test_bad_secret(self):
        r = self.engine.handle(entry(secret="wrong"))
        self.assertEqual(r.http_status, 401)
        self.assertIsNone(self.broker.position("XAUUSD"))

    def test_invalid_json(self):
        r = self.engine.handle_raw(b'{"secret":"x","signal":}')
        self.assertEqual(r.http_status, 400)

    def test_entry_then_close_pnl(self):
        r = self.engine.handle(entry())
        self.assertEqual(r.status, "accepted", r.detail)
        pos = self.broker.position("XAUUSD")
        self.assertEqual((pos.units, pos.stop_loss, pos.take_profit), (10, 3990.0, 4020.0))
        r = self.engine.handle(close(price=4020.0))
        self.assertEqual(r.status, "accepted", r.detail)
        self.assertAlmostEqual(self.broker.balance(), 10_200.0)

    def test_duplicate_alert_ignored(self):
        self.engine.handle(entry())
        r = self.engine.handle(entry())
        self.assertEqual(r.status, "duplicate")

    def test_stale_alert_rejected(self):
        old_bar = BAR_1H - 3 * 3600 * 1000
        r = self.engine.handle(entry(bar=old_bar))
        self.assertEqual(r.status, "rejected")
        self.assertIn("stale", r.detail)

    def test_symbol_whitelist(self):
        p = entry()
        p["signal"]["symbol"] = "EURUSD"
        self.assertEqual(self.engine.handle(p).status, "rejected")

    def test_qty_capped_by_risk(self):
        # 2.5% of 10k = 250 USD risk; sl 10 -> max 25 oz even if alert asks for 50
        r = self.engine.handle(entry(qty=50))
        self.assertEqual(r.status, "accepted")
        self.assertEqual(self.broker.position("XAUUSD").units, 25)
        self.assertIn("capped", r.detail)

    def test_qty_capped_by_max_units(self):
        self.cfg.max_units = 3
        self.engine.handle(entry(qty=5, sl=1.0))
        self.assertEqual(self.broker.position("XAUUSD").units, 3)

    def test_qty_capped_by_leverage(self):
        self.cfg.max_leverage = 1.0          # 10k balance / 4000 price -> 2 oz max notional
        self.engine.handle(entry(qty=10, sl=1.0))
        self.assertEqual(self.broker.position("XAUUSD").units, 2)

    def test_entry_without_take_profit(self):
        self.engine.handle(entry(tp=0))
        self.assertIsNone(self.broker.position("XAUUSD").take_profit)

    def test_update_stop_tightens_only(self):
        self.engine.handle(entry())                       # stop 3990
        ok = self.engine.handle(stop_update(3995.0, bar=BAR_1H + 1))
        self.assertEqual(ok.status, "accepted", ok.detail)
        self.assertEqual(self.broker.position("XAUUSD").stop_loss, 3995.0)
        loosen = self.engine.handle(stop_update(3980.0, bar=BAR_1H + 2))
        self.assertEqual(loosen.status, "rejected")
        self.assertEqual(self.broker.position("XAUUSD").stop_loss, 3995.0)

    def test_update_stop_wrong_side_rejected(self):
        self.engine.handle(entry())
        r = self.engine.handle(stop_update(4010.0, ref=4005.0, bar=BAR_1H + 1))
        self.assertEqual(r.status, "rejected")

    def test_update_stop_when_flat_ignored(self):
        self.assertEqual(self.engine.handle(stop_update(3995.0)).status, "ignored")

    def test_second_entry_rejected_while_open(self):
        self.engine.handle(entry())
        r = self.engine.handle(entry(action="sell", bar=BAR_1H + 1))
        self.assertEqual(r.status, "rejected")

    def test_close_when_flat_is_noop(self):
        r = self.engine.handle(close())
        self.assertEqual(r.status, "ignored")

    def test_close_wrong_side_is_noop(self):
        self.engine.handle(entry())
        self.assertEqual(self.engine.handle(close(action="close_short")).status, "ignored")
        self.assertIsNotNone(self.broker.position("XAUUSD"))

    def test_kill_switch(self):
        open(self.cfg.kill_switch_file, "w").close()
        r = self.engine.handle(entry())
        self.assertEqual(r.status, "rejected")
        self.assertIn("kill", r.detail)

    def test_max_trades_per_day(self):
        self.cfg.max_trades_per_day = 1
        self.engine.handle(entry())
        self.engine.handle(close(bar=BAR_1H + 1))
        r = self.engine.handle(entry(bar=BAR_1H + 2))
        self.assertEqual(r.status, "rejected")
        self.assertIn("max trades", r.detail)

    def test_daily_loss_limit(self):
        self.cfg.max_daily_loss_pct = 1.0
        self.engine.handle(entry(qty=10, sl=10))
        self.engine.handle(close(price=3985.0, bar=BAR_1H + 1))   # -150 USD = -1.5%
        r = self.engine.handle(entry(bar=BAR_1H + 2))
        self.assertEqual(r.status, "rejected")
        self.assertIn("daily loss", r.detail)

    def test_report(self):
        self.engine.handle(entry())
        self.engine.handle(close(price=4020.0))
        text = build_report(self.journal, NOW.date().isoformat())
        self.assertIn("+200.00", text)


class PaperStateTests(unittest.TestCase):
    def test_state_persists(self):
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "state.json")
            b = PaperBroker(1000, spread=0.3, state_file=f)
            b.open_market("XAUUSD", -1, 2, 4000.0, 5.0, 10.0)
            b2 = PaperBroker(1000, spread=0.3, state_file=f)
            pos = b2.position("XAUUSD")
            self.assertEqual(pos.units, -2)
            self.assertAlmostEqual(pos.avg_price, 3999.85)
            fill = b2.close("XAUUSD", 3990.0)
            self.assertAlmostEqual(fill.realized_pnl, (3990.15 - 3999.85) * -2, places=2)


class ConfigTests(unittest.TestCase):
    def test_live_requires_confirmation(self):
        c = Config(webhook_secret=SECRET, broker="oanda", oanda_env="live", allowed_symbols=("XAUUSD",),
                   oanda_account_id="a", oanda_token="t")
        with self.assertRaises(ValueError):
            c.validate()
        c.allow_live_trading = LIVE_CONFIRMATION
        c.validate()

    def test_short_secret_refused(self):
        with self.assertRaises(ValueError):
            Config(webhook_secret="short").validate()

    def test_allowlist_entries_validated(self):
        Config(webhook_secret=SECRET, ip_allowlist=("52.89.214.238", "52.89.214.0/24", "::1")).validate()
        with self.assertRaises(ValueError):
            Config(webhook_secret=SECRET, ip_allowlist=("not-an-ip",)).validate()

    def test_trusted_header_must_be_one_name(self):
        Config(webhook_secret=SECRET, trusted_ip_header="CF-Connecting-IP").validate()
        with self.assertRaises(ValueError):
            Config(webhook_secret=SECRET, trusted_ip_header="X-Real-IP, X-Forwarded-For").validate()

    def test_warns_when_allowlist_cannot_work_on_loopback(self):
        c = Config(webhook_secret=SECRET, host="127.0.0.1", ip_allowlist=("52.89.214.238",))
        self.assertTrue(any("TRUSTED_IP_HEADER" in w for w in c.warnings()))
        c.trusted_ip_header = "CF-Connecting-IP"
        self.assertEqual(c.warnings(), [])


class FakeResp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.content = json.dumps(body).encode()

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.calls = []
        self.fail_post = False
        self.position_units = "0"

    def post(self, url, json=None, timeout=None):
        import requests
        self.calls.append(("POST", url, json))
        if self.fail_post:
            raise requests.ConnectionError("boom")
        return FakeResp(201, {"orderFillTransaction": {"id": "42", "price": "4000.500", "units": json["order"]["units"]}})

    def get(self, url, timeout=None):
        self.calls.append(("GET", url, None))
        if url.endswith("/openTrades"):
            return FakeResp(200, {"trades": [{"id": "7", "instrument": "XAU_USD", "currentUnits": "5",
                                              "stopLossOrder": {"price": "3980.000"}}]})
        return FakeResp(200, {"position": {"long": {"units": self.position_units, "averagePrice": "4000.5"},
                                           "short": {"units": "0"}}})

    def put(self, url, json=None, timeout=None):
        self.calls.append(("PUT", url, json))
        if "/trades/" in url:
            return FakeResp(200, {"stopLossOrderTransaction": {"id": "50"}})
        return FakeResp(200, {"longOrderFillTransaction": {"id": "43", "price": "4010", "units": "-5", "pl": "47.5"}})


class OandaTests(unittest.TestCase):
    def setUp(self):
        try:
            import requests  # noqa: F401
        except ImportError:
            self.skipTest("requests not installed")
        self.s = FakeSession()
        self.b = OandaBroker("acct", "tok", "practice", session=self.s)

    def test_order_payload_has_stop_on_fill(self):
        f = self.b.open_market("XAUUSD", 1, 5, 4000.0, 12.5, 25.0)
        self.assertEqual(f.status, "filled")
        _, url, body = self.s.calls[0]
        self.assertTrue(url.endswith("/v3/accounts/acct/orders"))
        o = body["order"]
        self.assertEqual((o["instrument"], o["units"]), ("XAU_USD", "5"))
        self.assertEqual(o["stopLossOnFill"]["distance"], "12.500")
        self.assertEqual(o["takeProfitOnFill"]["price"], "4025.000")

    def test_network_error_verifies_instead_of_retrying(self):
        self.s.fail_post = True
        self.s.position_units = "5"
        f = self.b.open_market("XAUUSD", 1, 5, 4000.0, 12.5, 25.0)
        self.assertEqual(f.status, "unknown")
        self.assertEqual(sum(1 for c in self.s.calls if c[0] == "POST"), 1)

    def test_update_stop_moves_trade_stop(self):
        f = self.b.update_stop("XAUUSD", 3990.0)
        self.assertEqual(f.status, "filled")
        _, url, body = self.s.calls[-1]
        self.assertTrue(url.endswith("/trades/7/orders"))
        self.assertEqual(body["stopLoss"]["price"], "3990.000")

    def test_update_stop_refuses_to_loosen(self):
        f = self.b.update_stop("XAUUSD", 3970.0)
        self.assertEqual(f.status, "failed")
        self.assertFalse(any(c[0] == "PUT" for c in self.s.calls))

    def test_close_long(self):
        self.s.position_units = "5"
        f = self.b.close("XAUUSD")
        self.assertEqual((f.status, f.realized_pnl), ("filled", 47.5))
        self.assertEqual(self.s.calls[-1][2], {"longUnits": "ALL"})


class ServerTests(Base):
    def test_http_roundtrip(self):
        self.engine.clock = lambda: datetime.now(timezone.utc)
        bar = int((datetime.now(timezone.utc).timestamp() - 3600) * 1000)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.engine, self.cfg))
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            url = f"http://127.0.0.1:{srv.server_address[1]}"
            req = urllib.request.Request(url + "/webhook", data=json.dumps(entry(bar=bar)).encode(),
                                         headers={"Content-Type": "text/plain"})
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(json.load(resp)["status"], "accepted")
            with urllib.request.urlopen(url + "/status") as resp:
                self.assertEqual(json.load(resp)["position"]["units"], 10)
        finally:
            srv.shutdown()
            srv.server_close()


class IpAllowlistTests(Base):
    """The test server listens on 127.0.0.1, exactly like the bridge behind cloudflared."""
    TV = "52.89.214.238"

    def post(self, headers=None, **cfg):
        for k, v in cfg.items():
            setattr(self.cfg, k, v)
        with running_server(self.engine, self.cfg) as url:
            return http_post(url, entry(), headers)

    def test_spoofed_forwarded_for_rejected(self):
        code, _ = self.post({"X-Forwarded-For": self.TV}, ip_allowlist=(self.TV,))
        self.assertEqual(code, 403)
        self.assertIsNone(self.broker.position("XAUUSD"))

    def test_trusted_header_allowed_ip_reaches_engine(self):
        code, body = self.post({"CF-Connecting-IP": self.TV}, ip_allowlist=(self.TV,),
                               trusted_ip_header="CF-Connecting-IP")
        self.assertEqual((code, body["status"]), (200, "accepted"))

    def test_trusted_header_other_ip_rejected(self):
        code, _ = self.post({"CF-Connecting-IP": "1.2.3.4"}, ip_allowlist=(self.TV,),
                            trusted_ip_header="CF-Connecting-IP")
        self.assertEqual(code, 403)

    def test_trusted_header_missing_rejected(self):
        code, _ = self.post({"X-Forwarded-For": self.TV}, ip_allowlist=(self.TV,),
                            trusted_ip_header="CF-Connecting-IP")
        self.assertEqual(code, 403)

    def test_trusted_header_garbage_rejected(self):
        code, _ = self.post({"CF-Connecting-IP": "52.89.214.238, 1.2.3.4"}, ip_allowlist=(self.TV,),
                            trusted_ip_header="CF-Connecting-IP")
        self.assertEqual(code, 403)

    def test_cidr_allowlist(self):
        code, body = self.post({"CF-Connecting-IP": self.TV}, ip_allowlist=("52.89.214.0/24",),
                               trusted_ip_header="CF-Connecting-IP")
        self.assertEqual((code, body["status"]), (200, "accepted"))

    def test_no_allowlist_ignores_headers(self):
        code, body = self.post({"X-Forwarded-For": "1.2.3.4", "CF-Connecting-IP": "garbage"})
        self.assertEqual((code, body["status"]), (200, "accepted"))


if __name__ == "__main__":
    unittest.main()
