"""High-impact USD news calendar for XAUUSD (FOMC decisions, Non-Farm Payrolls, CPI).

The bundled file `data/high_impact_usd.csv` holds historical and scheduled release dates:
  * FOMC: federalreserve.gov meeting calendars (decision day = last day of the meeting,
    plus the emergency cuts of 2020-03-03 and 2020-03-15)
  * NFP (Employment Situation) and CPI: BLS release archives
    (bls.gov/bls/news-release/empsit.htm and cpi.htm)
"""
from __future__ import annotations

import csv
import os
from datetime import date

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "data", "high_impact_usd.csv")


def load_events(path: str = DEFAULT_PATH, kinds: tuple[str, ...] = ("FOMC", "NFP", "CPI")) -> list[date]:
    out = []
    with open(path, newline="") as fh:
        for row in csv.DictReader(fh):
            if row["event"] in kinds:
                out.append(date.fromisoformat(row["date"]))
    return sorted(set(out))
