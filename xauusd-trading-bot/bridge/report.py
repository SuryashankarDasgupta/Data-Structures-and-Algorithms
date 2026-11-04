r"""Daily review: realized P&L, orders, rejected/failed alerts.

Usage: python -m bridge.report [YYYY-MM-DD]     (defaults to today, UTC)
Schedule with cron, e.g.  5 0 * * *  cd /path && python -m bridge.report $(date -u -d yesterday +\%F)
"""
from __future__ import annotations

import sys
from collections import Counter

from .config import Config
from .journal import Journal, utc_now


def build_report(journal: Journal, day: str) -> str:
    orders = journal.orders_on(day)
    signals = journal.signals_on(day)
    realized = sum(o["realized_pnl"] or 0 for o in orders)
    opened = [o for o in orders if o["action"].startswith("open_")]
    closes = [o for o in orders if o["action"] == "close" and o["status"] == "filled"]
    failed = [o for o in orders if o["status"] != "filled"]
    by_status = Counter(s["status"] for s in signals)

    lines = [f"=== XAUUSD bridge report {day} (UTC) ===",
             f"Realized P&L      : {realized:+.2f} USD (net of modelled spread)",
             f"Entries / closes  : {len(opened)} / {len(closes)}",
             f"Failed/unverified : {len(failed)}",
             "Alerts            : " + (", ".join(f"{k}={v}" for k, v in sorted(by_status.items())) or "none"),
             "", "Orders:"]
    for o in orders:
        lines.append(f"  {o['ts'][11:19]} {o['action']:<10} {o['units'] or 0:>5} oz @ {o['price']}"
                     f"  SL {o['stop_loss']} TP {o['take_profit']} pnl {o['realized_pnl']} [{o['status']}]")
    problems = [s for s in signals if s["status"] in ("rejected", "error")]
    if problems:
        lines += ["", "Rejected / errors:"]
        lines += [f"  {s['received_at'][11:19]} {s['status']}: {s['reason']}" for s in problems]
    return "\n".join(lines)


def main() -> None:
    day = sys.argv[1] if len(sys.argv) > 1 else utc_now().date().isoformat()
    print(build_report(Journal(Config.from_env().journal_path), day))


if __name__ == "__main__":
    main()
