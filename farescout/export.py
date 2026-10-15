"""Build docs/deals.json, the file the dashboard reads."""

from __future__ import annotations

import json
import urllib.parse
from datetime import date, timedelta
from pathlib import Path

from .detect import Deal
from .regions import REGION_NAMES, region_for
from .travelpayouts import display_name


def money(amount: float, currency: str) -> str:
    cur = currency.lower()
    n = round(amount)
    if cur == "inr":
        # Indian grouping: 1,23,456
        s = str(abs(n))
        if len(s) > 3:
            head, tail = s[:-3], s[-3:]
            groups = []
            while len(head) > 2:
                groups.insert(0, head[-2:])
                head = head[:-2]
            if head:
                groups.insert(0, head)
            s = ",".join(groups) + "," + tail
        return f"₹{s}"
    symbol = {"usd": "$", "eur": "€", "gbp": "£"}.get(cur)
    return f"{symbol}{n:,}" if symbol else f"{n:,} {cur.upper()}"


def _place(ref: dict, code: str) -> dict:
    return ref["cities"].get(code) or ref["airports"].get(code) or {}


def deal_to_json(
    deal: Deal, ref: dict, verification: dict | None, google_url: str | None, history: list[tuple[str, float]]
) -> dict:
    f = deal.fare
    origin = _place(ref, deal.origin)
    dest = _place(ref, deal.destination)
    country_code = dest.get("country_code")
    depart = (f.get("departure_at") or "")[:10]
    ret = (f.get("return_at") or "")[:10]
    airline = f.get("airline") or ""
    link = f.get("link")
    if not google_url:
        q = f"Flights from {deal.origin} to {deal.destination} on {depart} through {ret}"
        google_url = f"https://www.google.com/travel/flights?q={urllib.parse.quote(q)}&curr={deal.currency.upper()}"
    v = verification or {"status": "unchecked", "live_price": None, "checked_at": None}
    out = {
        "id": f"{deal.origin}-{deal.destination}-{deal.month}" + ("-nonstop" if deal.nonstop else ""),
        "nonstop_deal": deal.nonstop,
        "origin": deal.origin,
        "origin_name": display_name(origin, deal.origin),
        "origin_airport": f.get("origin_airport") or deal.origin,
        "destination": deal.destination,
        "destination_name": display_name(dest, deal.destination),
        "destination_airport": f.get("destination_airport") or deal.destination,
        "country": country_code,
        "country_name": display_name(ref["countries"].get(country_code or ""), country_code or ""),
        "region": region_for(country_code),
        "month": deal.month,
        "currency": deal.currency,
        "price": deal.price,
        "price_label": money(deal.price, deal.currency),
        "baseline": deal.baseline,
        "baseline_label": money(deal.baseline, deal.currency),
        "baseline_source": deal.baseline_source,
        "off": deal.off,
        "mistake": deal.mistake,
        "airline": airline,
        "airline_name": display_name(ref["airlines"].get(airline), airline or "Various airlines"),
        "transfers": f.get("transfers"),
        "return_transfers": f.get("return_transfers"),
        "depart_date": depart,
        "return_date": ret,
        "duration_minutes": f.get("duration"),
        "aviasales_url": f"https://www.aviasales.com{link}" if link else None,
        "google_url": google_url,
        "verified": {"status": v["status"], "live_price": v.get("live_price"), "checked_at": v.get("checked_at")},
        "price_label_live": money(v["live_price"], deal.currency) if v.get("live_price") else None,
        "history": [[d, p] for d, p in history],
    }
    return out


def write_deals_json(
    path: Path,
    generated_at: str,
    origins: list[dict],
    deals: list[dict],
    stats: dict,
    posts: list[dict] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": generated_at,
        "sample": False,
        "origins": origins,
        "regions": REGION_NAMES,
        "stats": stats,
        "deals": deals,
        "posts": posts or [],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def month_range(today: date, months: int) -> list[str]:
    out = []
    y, m = today.year, today.month
    for _ in range(months):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def history_window_start(today: date, days: int) -> date:
    return today - timedelta(days=days)
