"""SQLite journal: every alert, decision and order is recorded for daily review."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at TEXT NOT NULL,
    dedupe_key TEXT,
    action TEXT,
    status TEXT NOT NULL,          -- accepted | rejected | error | duplicate
    reason TEXT,
    raw TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_signals_dedupe
    ON signals(dedupe_key) WHERE status = 'accepted';
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    day TEXT NOT NULL,
    symbol TEXT NOT NULL,
    action TEXT NOT NULL,          -- open_long | open_short | close
    units INTEGER,
    price REAL,
    stop_loss REAL,
    take_profit REAL,
    realized_pnl REAL,
    broker_ref TEXT,
    status TEXT NOT NULL           -- filled | unknown | failed
);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL);
"""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Journal:
    def __init__(self, path: str = ":memory:"):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)

    def close(self) -> None:
        self._db.close()

    # --- signals -------------------------------------------------------
    def is_duplicate(self, dedupe_key: str) -> bool:
        with self._lock:
            row = self._db.execute(
                "SELECT 1 FROM signals WHERE dedupe_key=? AND status='accepted'", (dedupe_key,)
            ).fetchone()
        return row is not None

    def log_signal(self, status: str, reason: str, raw: Any,
                   dedupe_key: Optional[str] = None, action: Optional[str] = None) -> None:
        if isinstance(raw, dict) and "secret" in raw:
            raw = {**raw, "secret": "***"}
        raw_s = raw if isinstance(raw, str) else json.dumps(raw, default=str)
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO signals(received_at, dedupe_key, action, status, reason, raw) "
                "VALUES (?,?,?,?,?,?)",
                (utc_now().isoformat(), dedupe_key, action, status, reason, raw_s[:4000]),
            )

    # --- orders --------------------------------------------------------
    def log_order(self, symbol: str, action: str, units: int, price: Optional[float],
                  status: str, stop_loss: Optional[float] = None,
                  take_profit: Optional[float] = None, realized_pnl: Optional[float] = None,
                  broker_ref: str = "", now: Optional[datetime] = None) -> None:
        now = now or utc_now()
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO orders(ts, day, symbol, action, units, price, stop_loss, take_profit,"
                " realized_pnl, broker_ref, status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (now.isoformat(), now.date().isoformat(), symbol, action, units, price,
                 stop_loss, take_profit, realized_pnl, broker_ref, status),
            )

    def entries_on(self, day: str) -> int:
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(*) FROM orders WHERE day=? AND action LIKE 'open_%' "
                "AND status IN ('filled','unknown')", (day,)
            ).fetchone()
        return int(row[0])

    def orders_on(self, day: str) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute("SELECT * FROM orders WHERE day=? ORDER BY id", (day,)).fetchall()

    def signals_on(self, day: str) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(
                "SELECT * FROM signals WHERE substr(received_at,1,10)=? ORDER BY id", (day,)
            ).fetchall()

    # --- key/value -----------------------------------------------------
    def get(self, key: str) -> Optional[str]:
        with self._lock:
            row = self._db.execute("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
        return row[0] if row else None

    def set(self, key: str, value: str) -> None:
        with self._lock, self._db:
            self._db.execute("INSERT INTO kv(k, v) VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                             (key, value))
