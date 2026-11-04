"""High-impact USD news calendar for the bridge (FOMC, NFP, CPI).

Events come from data/high_impact_usd.csv (date,event,description). Release times are the official
New York times: NFP and CPI 08:30, FOMC statement 14:00 (converted to UTC with DST handled).
An optional `time_utc` column (HH:MM) overrides the default time for a row.

Update upcoming dates with:  python -m bridge.news update   (ForexFactory weekly feed, optional)
or by appending rows to the CSV by hand from federalreserve.gov / bls.gov schedules.
Then copy them into the Pine script with:  python -m bridge.news pine
"""
from __future__ import annotations

import csv
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
DEFAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "data", "high_impact_usd.csv")
NY_RELEASE_TIME = {"NFP": time(8, 30), "CPI": time(8, 30), "FOMC": time(14, 0)}
FF_FEED = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
# ForexFactory titles that map to our event kinds
FF_TITLES = {
    "Non-Farm Employment Change": "NFP",
    "CPI m/m": "CPI",
    "Federal Funds Rate": "FOMC",
}


@dataclass(frozen=True, order=True)
class NewsEvent:
    at: datetime          # UTC
    kind: str
    description: str = ""

    def label(self) -> str:
        return f"{self.kind} {self.at:%Y-%m-%d %H:%M} UTC"


def _event_time(d: date, kind: str, time_utc: str = "") -> datetime:
    if time_utc:
        hh, mm = (int(x) for x in time_utc.split(":"))
        return datetime(d.year, d.month, d.day, hh, mm, tzinfo=timezone.utc)
    local = datetime.combine(d, NY_RELEASE_TIME.get(kind, time(8, 30)), tzinfo=NY)
    return local.astimezone(timezone.utc)


class NewsCalendar:
    def __init__(self, events: Iterable[NewsEvent]):
        self.events = sorted(set(events))

    @classmethod
    def load(cls, path: str = DEFAULT_PATH, kinds: Iterable[str] = ("FOMC", "NFP", "CPI")) -> "NewsCalendar":
        kinds = set(kinds)
        out = []
        if os.path.exists(path):
            with open(path, newline="") as fh:
                for row in csv.DictReader(fh):
                    if row["event"] in kinds:
                        d = date.fromisoformat(row["date"])
                        out.append(NewsEvent(_event_time(d, row["event"], row.get("time_utc") or ""),
                                             row["event"], row.get("description", "")))
        return cls(out)

    def upcoming(self, now: datetime, hours_ahead: float, minutes_after: float = 0.0) -> list[NewsEvent]:
        """Events in [now - minutes_after, now + hours_ahead]."""
        lo, hi = now - timedelta(minutes=minutes_after), now + timedelta(hours=hours_ahead)
        return [e for e in self.events if lo <= e.at <= hi]

    def next_events(self, now: datetime, n: int = 3) -> list[NewsEvent]:
        return [e for e in self.events if e.at >= now][:n]

    def last_event(self) -> Optional[NewsEvent]:
        return self.events[-1] if self.events else None

    def is_stale(self, now: datetime, days: int = 21) -> bool:
        """True if the calendar has no NFP or CPI in the next `days` days (they occur monthly)."""
        hi = now + timedelta(days=days)
        return not any(now <= e.at <= hi and e.kind in ("NFP", "CPI") for e in self.events)


# ───────────────────────── optional updater ─────────────────────────
def parse_forexfactory(items: list[dict]) -> list[tuple[str, str, str, str]]:
    """Return CSV rows (date, event, description, time_utc) for high-impact USD events we track."""
    rows = []
    for it in items:
        if it.get("country") != "USD" or it.get("impact") != "High":
            continue
        kind = FF_TITLES.get(str(it.get("title", "")).strip())
        if not kind:
            continue
        try:
            at = datetime.fromisoformat(str(it["date"])).astimezone(timezone.utc)
        except (KeyError, ValueError):
            continue
        ny_date = at.astimezone(NY).date()
        rows.append((ny_date.isoformat(), kind, f"{it['title']} (ForexFactory)", at.strftime("%H:%M")))
    return rows


def merge_rows(path: str, new_rows: list[tuple[str, str, str, str]]) -> int:
    existing = []
    if os.path.exists(path):
        with open(path, newline="") as fh:
            existing = list(csv.DictReader(fh))
    have = {(r["date"], r["event"]) for r in existing}
    added = [r for r in new_rows if (r[0], r[1]) not in have]
    if not added:
        return 0
    rows = [(r["date"], r["event"], r.get("description", ""), r.get("time_utc", "")) for r in existing] + added
    rows.sort()
    tmp = path + ".tmp"
    with open(tmp, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "event", "description", "time_utc"])
        w.writerows(rows)
    os.replace(tmp, path)
    return len(added)


PINE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "pine", "xauusd_daily_trend.pine")


def sync_pine(csv_path: str = DEFAULT_PATH, pine_path: str = PINE_PATH) -> dict[str, int]:
    """Rewrite the FOMC_DATES / NFP_DATES / CPI_DATES constants in the Pine script from the CSV."""
    import re
    dates: dict[str, list[str]] = {"FOMC": [], "NFP": [], "CPI": []}
    with open(csv_path, newline="") as fh:
        for row in csv.DictReader(fh):
            if row["event"] in dates:
                dates[row["event"]].append(row["date"].replace("-", ""))
    with open(pine_path) as fh:
        src = fh.read()
    for kind, vals in dates.items():
        const = f"{kind}_DATES"
        pattern = re.compile(rf'^({const}\s*=\s*)"[0-9,]*"$', re.M)
        if not pattern.search(src):
            raise ValueError(f"{const} constant not found in {pine_path}")
        joined = ",".join(sorted(set(vals)))
        src = pattern.sub(lambda m: f'{m.group(1)}"{joined}"', src)
    with open(pine_path, "w") as fh:
        fh.write(src)
    return {k: len(set(v)) for k, v in dates.items()}


def main(argv: list[str]) -> None:
    cmd = argv[1] if len(argv) > 1 else "show"
    path = os.environ.get("NEWS_CALENDAR", DEFAULT_PATH)
    if cmd == "pine":
        print("Pine calendar updated:", sync_pine(path))
        return
    if cmd == "update":
        import requests
        r = requests.get(FF_FEED, timeout=15, headers={"User-Agent": "xauusd-bridge/1.0"})
        r.raise_for_status()
        n = merge_rows(path, parse_forexfactory(r.json()))
        print(f"added {n} event(s) to {path}")
    cal = NewsCalendar.load(path)
    now = datetime.now(timezone.utc)
    print("next high-impact events:")
    for e in cal.next_events(now, 5):
        print("  ", e.label(), "-", e.description)
    if cal.is_stale(now):
        print("WARNING: calendar has no NFP/CPI in the next 3 weeks; update it", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv)
