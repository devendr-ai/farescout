"""Decide which fares are deals.

A fare is a deal when it is far below its own route's normal price:
  - history baseline: median daily low for the same route and departure month over
    the last `history_days`, once there are `min_history_days` of data;
  - cold start: median of the same route's other departure months in this scan.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median
from typing import Callable

from .config import DealRules

# (origin, destination, month) -> fare row from the API
Fares = dict[tuple[str, str, str], dict]
# (origin, destination, month, currency, since, before) -> [(day, price), ...]
HistoryFn = Callable[[str, str, str, str, date, date], list[tuple[str, float]]]


@dataclass
class Deal:
    origin: str
    destination: str
    month: str
    currency: str
    price: float
    baseline: float
    baseline_source: str  # "history" | "other_months"
    off: float  # 0.55 means 55% below baseline
    mistake: bool
    fare: dict
    nonstop: bool = False  # found by the nonstop-only scan, compared with nonstop history

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.origin, self.destination, self.month)


def baseline_for(
    key: tuple[str, str, str],
    currency: str,
    fares: Fares,
    history: HistoryFn,
    rules: DealRules,
    today: date,
) -> tuple[float, str] | None:
    origin, dest, month = key
    since = today - timedelta(days=rules.history_days)
    past = history(origin, dest, month, currency, since, today)
    if len(past) >= rules.min_history_days:
        return median(p for _, p in past), "history"

    others = [f["price"] for (o, d, m), f in fares.items() if o == origin and d == dest and m != month]
    if len(others) >= rules.min_other_months:
        return median(others), "other_months"
    return None


def find_deals(
    fares: Fares, currencies: dict[str, str], history: HistoryFn, rules: DealRules, today: date, nonstop: bool = False
) -> list[Deal]:
    """Return deals sorted by biggest discount first."""
    deals: list[Deal] = []
    for key, fare in fares.items():
        currency = currencies[key[0]]
        base = baseline_for(key, currency, fares, history, rules, today)
        if base is None:
            continue
        baseline, source = base
        price = float(fare["price"])
        if baseline <= 0:
            continue
        off = 1 - price / baseline
        if off < rules.min_off:
            continue
        deals.append(
            Deal(
                origin=key[0],
                destination=key[1],
                month=key[2],
                currency=currency,
                price=price,
                baseline=round(baseline, 2),
                baseline_source=source,
                off=round(off, 4),
                mistake=off >= rules.mistake_off,
                fare=fare,
                nonstop=nonstop,
            )
        )
    deals.sort(key=lambda d: d.off, reverse=True)
    return deals
