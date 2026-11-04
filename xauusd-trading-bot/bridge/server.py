"""Minimal HTTP server for TradingView webhooks (standard library only).

Endpoints
  POST /webhook  - TradingView alert body
  GET  /health   - liveness
  GET  /status   - balance, open position, today's activity

Run:  WEBHOOK_SECRET=... python -m bridge.server
Note: TradingView only delivers webhooks to ports 80/443, so put this behind a reverse proxy
(Caddy/nginx with TLS) or a tunnel (cloudflared/ngrok).
"""
from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .brokers import make_broker
from .config import Config
from .engine import Engine
from .journal import Journal, utc_now
from .news import DEFAULT_PATH as NEWS_DEFAULT, NewsCalendar

MAX_BODY = 16 * 1024
log = logging.getLogger("bridge")


def make_handler(engine: Engine, cfg: Config):
    class Handler(BaseHTTPRequestHandler):
        server_version = "xau-bridge/1.0"

        def _send(self, code: int, payload: dict) -> None:
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _client_ip(self) -> str:
            fwd = self.headers.get("X-Forwarded-For")
            return fwd.split(",")[0].strip() if fwd else self.client_address[0]

        def do_GET(self):  # noqa: N802
            if self.path == "/health":
                return self._send(200, {"ok": True})
            if self.path == "/status":
                day = utc_now().date().isoformat()
                pos = engine.broker.position(cfg.allowed_symbols[0])
                return self._send(200, {
                    "broker": cfg.broker,
                    "balance": engine.broker.balance(),
                    "position": pos.__dict__ if pos else None,
                    "entries_today": engine.journal.entries_on(day),
                    "next_news": [e.label() for e in engine.news.next_events(utc_now())] if engine.news else [],
                    "news_calendar_stale": engine.news.is_stale(utc_now()) if engine.news else None,
                })
            self._send(404, {"error": "not found"})

        def do_POST(self):  # noqa: N802
            if self.path != "/webhook":
                return self._send(404, {"error": "not found"})
            if cfg.ip_allowlist and self._client_ip() not in cfg.ip_allowlist:
                return self._send(403, {"error": "forbidden"})
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY:
                return self._send(413 if length > MAX_BODY else 400, {"error": "bad body size"})
            result = engine.handle_raw(self.rfile.read(length))
            self._send(result.http_status, result.as_dict())

        def log_message(self, fmt, *args):
            log.info("%s %s", self._client_ip(), fmt % args)

    return Handler


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = Config.from_env()
    cfg.validate()
    news = None
    if cfg.news_block_hours > 0:
        news = NewsCalendar.load(cfg.news_calendar or NEWS_DEFAULT, cfg.news_events)
        if news.is_stale(utc_now()):
            log.warning("news calendar has no NFP/CPI in the next 3 weeks: run `python -m bridge.news update` "
                        "or add dates to %s", cfg.news_calendar or NEWS_DEFAULT)
        nxt = news.next_events(utc_now(), 1)
        log.info("news guard on (%sh before, %smin after); next: %s", cfg.news_block_hours,
                 cfg.news_block_after_min, nxt[0].label() if nxt else "none in calendar")
    engine = Engine(cfg, make_broker(cfg), Journal(cfg.journal_path), news=news)
    srv = ThreadingHTTPServer((cfg.host, cfg.port), make_handler(engine, cfg))
    log.info("listening on %s:%s broker=%s", cfg.host, cfg.port,
             cfg.broker + (f"/{cfg.oanda_env}" if cfg.broker == "oanda" else ""))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
