"""Broker adapters. PaperBroker is the default; OandaBroker talks to the OANDA v20 REST API."""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from typing import Optional, Protocol

log = logging.getLogger(__name__)


@dataclass
class Position:
    symbol: str
    units: int                 # signed: >0 long, <0 short
    avg_price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None


@dataclass
class Fill:
    status: str                # filled | unknown | failed
    price: Optional[float] = None
    units: int = 0
    realized_pnl: Optional[float] = None
    broker_ref: str = ""
    message: str = ""


class Broker(Protocol):
    def balance(self) -> float: ...
    def position(self, symbol: str) -> Optional[Position]: ...
    def open_market(self, symbol: str, side: int, units: int, ref_price: float,
                    sl_dist: float, tp_dist: float) -> Fill: ...
    def close(self, symbol: str, price_hint: Optional[float] = None) -> Fill: ...


# ───────────────────────────── Paper ─────────────────────────────
class PaperBroker:
    """Simulated account. Fills at the alert price +/- half the spread.

    Stop-loss / take-profit hits are not simulated intrabar here: the Pine strategy sends a
    close alert carrying {{strategy.order.price}} when TradingView fills its exit, and that
    price is used. State persists to a JSON file so restarts keep the open position.
    """

    def __init__(self, start_balance: float = 10_000.0, spread: float = 0.30,
                 state_file: Optional[str] = None):
        self.spread = spread
        self.state_file = state_file
        self._balance = start_balance
        self._positions: dict[str, Position] = {}
        self._seq = 0
        self._load()

    def _load(self) -> None:
        if self.state_file and os.path.exists(self.state_file):
            with open(self.state_file) as fh:
                st = json.load(fh)
            self._balance = st["balance"]
            self._seq = st.get("seq", 0)
            self._positions = {k: Position(**v) for k, v in st.get("positions", {}).items()}

    def _save(self) -> None:
        if not self.state_file:
            return
        tmp = self.state_file + ".tmp"
        with open(tmp, "w") as fh:
            json.dump({"balance": self._balance, "seq": self._seq,
                       "positions": {k: asdict(v) for k, v in self._positions.items()}}, fh, indent=2)
        os.replace(tmp, self.state_file)

    def balance(self) -> float:
        return self._balance

    def position(self, symbol: str) -> Optional[Position]:
        return self._positions.get(symbol)

    def open_market(self, symbol, side, units, ref_price, sl_dist, tp_dist) -> Fill:
        if symbol in self._positions:
            return Fill("failed", message="position already open")
        price = round(ref_price + side * self.spread / 2, 3)
        sl = round(price - side * sl_dist, 3)
        tp = round(price + side * tp_dist, 3) if tp_dist > 0 else None
        self._seq += 1
        self._positions[symbol] = Position(symbol, side * units, price, sl, tp)
        self._save()
        return Fill("filled", price=price, units=side * units, broker_ref=f"paper-{self._seq}")

    def close(self, symbol, price_hint=None) -> Fill:
        pos = self._positions.get(symbol)
        if pos is None:
            return Fill("failed", message="no open position")
        if price_hint is None:
            return Fill("failed", message="paper broker needs a price to close")
        side = 1 if pos.units > 0 else -1
        price = round(price_hint - side * self.spread / 2, 3)
        pnl = round((price - pos.avg_price) * pos.units, 2)
        self._balance = round(self._balance + pnl, 2)
        del self._positions[symbol]
        self._seq += 1
        self._save()
        return Fill("filled", price=price, units=-pos.units, realized_pnl=pnl,
                    broker_ref=f"paper-{self._seq}")


# ───────────────────────────── OANDA ─────────────────────────────
OANDA_HOSTS = {
    "practice": "https://api-fxpractice.oanda.com",
    "live": "https://api-fxtrade.oanda.com",
}
OANDA_INSTRUMENTS = {"XAUUSD": "XAU_USD"}


class OandaBroker:
    """OANDA v20 adapter. Stop-loss is attached on fill (by distance) so a position is never
    unprotected. On a network error while placing an order we do NOT retry blindly: we query
    the position and report status 'unknown' if something was filled."""

    def __init__(self, account_id: str, token: str, env: str = "practice", session=None,
                 timeout: float = 10.0):
        import requests  # imported lazily so paper mode has no dependency

        self.account_id = account_id
        self.base = OANDA_HOSTS[env]
        self.timeout = timeout
        self.http = session or requests.Session()
        self.http.headers.update({"Authorization": f"Bearer {token}",
                                  "Content-Type": "application/json"})
        self._req_exc = requests.RequestException

    def _inst(self, symbol: str) -> str:
        return OANDA_INSTRUMENTS.get(symbol, symbol)

    def _url(self, path: str) -> str:
        return f"{self.base}/v3/accounts/{self.account_id}{path}"

    def balance(self) -> float:
        r = self.http.get(self._url("/summary"), timeout=self.timeout)
        r.raise_for_status()
        return float(r.json()["account"]["balance"])

    def position(self, symbol: str) -> Optional[Position]:
        r = self.http.get(self._url(f"/positions/{self._inst(symbol)}"), timeout=self.timeout)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        p = r.json()["position"]
        long_u, short_u = int(float(p["long"]["units"])), int(float(p["short"]["units"]))
        if long_u:
            return Position(symbol, long_u, float(p["long"]["averagePrice"]))
        if short_u:
            return Position(symbol, short_u, float(p["short"]["averagePrice"]))
        return None

    def open_market(self, symbol, side, units, ref_price, sl_dist, tp_dist) -> Fill:
        order = {
            "type": "MARKET",
            "instrument": self._inst(symbol),
            "units": str(side * units),
            "timeInForce": "FOK",
            "positionFill": "DEFAULT",
            "stopLossOnFill": {"distance": f"{sl_dist:.3f}", "timeInForce": "GTC"},
        }
        if tp_dist > 0:
            order["takeProfitOnFill"] = {"price": f"{ref_price + side * tp_dist:.3f}",
                                         "timeInForce": "GTC"}
        try:
            r = self.http.post(self._url("/orders"), json={"order": order}, timeout=self.timeout)
        except self._req_exc as exc:
            log.error("order request failed, verifying position: %s", exc)
            return self._verify_after_error(symbol, side, str(exc))
        body = r.json() if r.content else {}
        fill = body.get("orderFillTransaction")
        if r.status_code >= 400 or not fill:
            reason = body.get("orderCancelTransaction", {}).get("reason") or body.get("errorMessage") \
                or f"HTTP {r.status_code}"
            return Fill("failed", message=str(reason))
        return Fill("filled", price=float(fill["price"]), units=int(float(fill["units"])),
                    broker_ref=str(fill.get("id", "")))

    def _verify_after_error(self, symbol: str, side: int, err: str) -> Fill:
        try:
            pos = self.position(symbol)
        except Exception as exc:  # noqa: BLE001
            return Fill("unknown", message=f"{err}; position check also failed: {exc}")
        if pos and (pos.units > 0) == (side > 0):
            return Fill("unknown", price=pos.avg_price, units=pos.units,
                        message=f"{err}; position exists, treating as filled")
        return Fill("failed", message=f"{err}; no position found")

    def close(self, symbol, price_hint=None) -> Fill:
        pos = self.position(symbol)
        if pos is None:
            return Fill("failed", message="no open position")
        body = {"longUnits": "ALL"} if pos.units > 0 else {"shortUnits": "ALL"}
        r = self.http.put(self._url(f"/positions/{self._inst(symbol)}/close"), json=body,
                          timeout=self.timeout)
        data = r.json() if r.content else {}
        tx = data.get("longOrderFillTransaction") or data.get("shortOrderFillTransaction")
        if r.status_code >= 400 or not tx:
            return Fill("failed", message=data.get("errorMessage", f"HTTP {r.status_code}"))
        return Fill("filled", price=float(tx["price"]), units=int(float(tx["units"])),
                    realized_pnl=float(tx.get("pl", 0.0)), broker_ref=str(tx.get("id", "")))


def make_broker(cfg) -> Broker:
    if cfg.broker == "oanda":
        return OandaBroker(cfg.oanda_account_id, cfg.oanda_token, cfg.oanda_env)
    return PaperBroker(cfg.paper_start_balance, cfg.paper_spread, cfg.paper_state_file)
