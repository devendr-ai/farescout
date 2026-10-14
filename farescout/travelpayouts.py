"""Client for the Travelpayouts (Aviasales) Data API.

Docs: https://support.travelpayouts.com/hc/en-us/articles/203956163-Aviasales-Data-API
Prices are cached from searches Aviasales users ran in the last 48 hours, so they can
be stale. Treat them as candidates and confirm the best ones live (see verify.py).
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.travelpayouts.com"
USER_AGENT = "farescout/0.1 (+personal fare tracker)"


class TravelpayoutsError(RuntimeError):
    pass


def _get_json(url: str, token: str | None = None, timeout: int = 30, retries: int = 3):
    headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}
    if token:
        headers["X-Access-Token"] = token
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                last_error = e
                time.sleep(2 * 2**attempt)
                continue
            body = e.read().decode(errors="replace")[:300]
            raise TravelpayoutsError(f"HTTP {e.code} from {url.split('?')[0]}: {body}") from e
        except urllib.error.URLError as e:
            last_error = e
            time.sleep(2 * 2**attempt)
    raise TravelpayoutsError(f"{url.split('?')[0]} failed after {retries} tries: {last_error}")


def cheapest_by_destination(origin: str, month: str, currency: str, market: str, token: str) -> list[dict]:
    """Cheapest roundtrip per destination from `origin`, departing in `month` (YYYY-MM)."""
    params = {
        "origin": origin,
        "departure_at": month,
        "one_way": "false",
        "unique": "true",
        "sorting": "price",
        "direct": "false",
        "limit": 1000,
        "currency": currency,
        "market": market,
    }
    data = _get_json(f"{API}/aviasales/v3/prices_for_dates?{urllib.parse.urlencode(params)}", token)
    if not data.get("success", False):
        raise TravelpayoutsError(f"prices_for_dates {origin} {month}: {data.get('error') or data}")
    # unique=true should already give one row per destination; keep the cheapest just in case.
    best: dict[str, dict] = {}
    for row in data.get("data") or []:
        dest = row.get("destination")
        price = row.get("price")
        if not dest or not price or dest == origin:
            continue
        if dest not in best or price < best[dest]["price"]:
            best[dest] = row
    return list(best.values())


REFERENCE_KINDS = ("cities", "airports", "countries", "airlines")


def load_reference(ref_dir: Path, max_age_days: int = 30) -> dict[str, dict[str, dict]]:
    """City, airport, country and airline names, keyed by code. Cached on disk."""
    ref_dir.mkdir(parents=True, exist_ok=True)
    out: dict[str, dict[str, dict]] = {}
    for kind in REFERENCE_KINDS:
        path = ref_dir / f"{kind}.json"
        fresh = path.exists() and time.time() - path.stat().st_mtime < max_age_days * 86400
        if not fresh:
            try:
                rows = _get_json(f"{API}/data/en/{kind}.json")
                path.write_text(json.dumps(rows), encoding="utf-8")
            except TravelpayoutsError:
                if not path.exists():
                    raise
        rows = json.loads(path.read_text(encoding="utf-8"))
        out[kind] = {r["code"]: r for r in rows if r.get("code")}
    return out


def display_name(entry: dict | None, fallback: str) -> str:
    if not entry:
        return fallback
    return entry.get("name") or (entry.get("name_translations") or {}).get("en") or fallback
