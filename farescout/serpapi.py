"""Live price checks through SerpApi's Google Flights API, for possible mistake fares only.

The free plan has 250 searches a month, so every search is budgeted (see config.toml
[serpapi]). Set SERPAPI_API_KEY to enable. Docs: https://serpapi.com/google-flights-api
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

from .detect import Deal

log = logging.getLogger(__name__)
SEARCH_URL = "https://serpapi.com/search.json"
ACCOUNT_URL = "https://serpapi.com/account.json"


def api_key() -> str | None:
    return os.environ.get("SERPAPI_API_KEY") or None


def _get(url: str, params: dict, timeout: int = 60) -> dict:
    req = urllib.request.Request(f"{url}?{urllib.parse.urlencode(params)}", headers={"User-Agent": "farescout/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            return json.load(e)
        except ValueError:
            return {"error": f"HTTP {e.code}"}


def searches_left(key: str) -> int | None:
    """Searches left this month according to SerpApi. The account call is free."""
    try:
        data = _get(ACCOUNT_URL, {"api_key": key}, timeout=20)
    except (urllib.error.URLError, OSError, ValueError) as e:
        log.warning("SerpApi account check failed: %s", type(e).__name__)
        return None
    left = data.get("total_searches_left", data.get("plan_searches_left"))
    return int(left) if isinstance(left, (int, float)) else None


def check(deal: Deal, key: str, tolerance: float) -> dict:
    """Search the exact trip on Google Flights via SerpApi.

    Returns {status, live_price, url, price_level, typical_low, typical_high}.
    Status: confirmed | higher | error.
    """
    f = deal.fare
    params = {
        "engine": "google_flights",
        "departure_id": f.get("origin_airport") or deal.origin,
        "arrival_id": f.get("destination_airport") or deal.destination,
        "outbound_date": (f.get("departure_at") or "")[:10],
        "return_date": (f.get("return_at") or "")[:10],
        "type": 1,
        "currency": deal.currency.upper(),
        "hl": "en",
        "gl": "in" if deal.currency.lower() == "inr" else "us",
        "stops": 1 if deal.nonstop else 0,
        "api_key": key,
    }
    out = {"status": "error", "live_price": None, "url": None, "price_level": None, "typical_low": None, "typical_high": None}
    try:
        data = _get(SEARCH_URL, params)
    except (urllib.error.URLError, OSError, ValueError) as e:
        log.warning("SerpApi search failed for %s-%s: %s", deal.origin, deal.destination, type(e).__name__)
        return out
    out["url"] = (data.get("search_metadata") or {}).get("google_flights_url")
    if data.get("error"):
        # e.g. "Google Flights hasn't returned any results for this query." Not proof it sold out.
        log.warning("SerpApi %s-%s: %s", deal.origin, deal.destination, data["error"])
        return out
    insights = data.get("price_insights") or {}
    out["price_level"] = insights.get("price_level")
    typical = insights.get("typical_price_range") or []
    if len(typical) == 2:
        out["typical_low"], out["typical_high"] = float(typical[0]), float(typical[1])
    prices = [o["price"] for o in (data.get("best_flights") or []) + (data.get("other_flights") or []) if o.get("price")]
    if not prices and insights.get("lowest_price"):
        prices = [insights["lowest_price"]]
    if not prices:
        return out
    live = float(min(prices))
    out["live_price"] = live
    out["status"] = "confirmed" if live <= deal.price * (1 + tolerance) else "higher"
    return out
