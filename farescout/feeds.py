"""Read free deal-site RSS/Atom feeds and keep posts that leave from your home airports.

Only feeds that serve plainly to a script are used. A feed that answers with an error,
a rate limit or a bot check is skipped for that run, never worked around.
"""

from __future__ import annotations

import html
import logging
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

log = logging.getLogger(__name__)
USER_AGENT = "farescout/0.1 (+personal fare tracker)"
ATOM = "{http://www.w3.org/2005/Atom}"

ERROR_FARE = re.compile(r"\b(error|mistake)\s+fares?\b|\bprice\s+error\b|\bfare\s+glitch\b", re.I)
PRICE = re.compile(r"([$€£₹])\s?(\d[\d,]*(?:\.\d+)?)|(\d[\d,]*)\s?(USD|EUR|INR)\b")


def fetch_feed(url: str, timeout: int = 20) -> list[dict]:
    """Items as {title, url, published (aware datetime or None)}. Empty list on any failure."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        log.warning("feed %s skipped: %s", urlparse(url).netloc, e)
        return []
    try:
        return parse_feed(body)
    except ET.ParseError as e:
        log.warning("feed %s skipped: not valid XML (%s)", urlparse(url).netloc, e)
        return []


def parse_feed(body: bytes) -> list[dict]:
    """Parse RSS 2.0 or Atom. Raises ET.ParseError on bad XML."""
    root = ET.fromstring(body)
    items = []
    for node in root.iter("item"):  # RSS 2.0
        items.append(
            {
                "title": _text(node.find("title")),
                "url": _text(node.find("link")),
                "published": _rss_date(_text(node.find("pubDate"))),
            }
        )
    for node in root.iter(f"{ATOM}entry"):  # Atom
        link = node.find(f"{ATOM}link")
        items.append(
            {
                "title": _text(node.find(f"{ATOM}title")),
                "url": link.get("href", "") if link is not None else "",
                "published": _iso_date(_text(node.find(f"{ATOM}updated")) or _text(node.find(f"{ATOM}published"))),
            }
        )
    return [i for i in items if i["title"] and i["url"]]


def _text(node) -> str:
    return html.unescape((node.text or "").strip()) if node is not None else ""


def _rss_date(s: str) -> datetime | None:
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _iso_date(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def origin_patterns(origins: dict[str, list[str]]) -> dict[str, re.Pattern]:
    """{code: [names]} -> {code: regex matching the code or any name as whole words}."""
    out = {}
    for code, names in origins.items():
        terms = [re.escape(code)] + [re.escape(n) for n in names if n]
        out[code] = re.compile(r"(?<![\w-])(" + "|".join(terms) + r")(?![\w-])", re.I)
    return out


_FROM = re.compile(r"\bfrom\s+(.+?)(?:\s+(?:to|–|—|-)\s+|$)", re.I)
_SPLIT = re.compile(r"\s+(?:to|–|—|-)\s+", re.I)


def departure_part(title: str) -> str:
    """The departure side of a deal title, so destinations don't count as home airports.

    "Delta: San Francisco – Porto, Portugal. $711"   -> "San Francisco"
    "Cheap flights from Brussels to Los Angeles"     -> "Brussels"
    "Business Class Deal: Brussels to Hong Kong"     -> "Brussels"
    """
    m = _FROM.search(title)
    if m:
        return m.group(1)
    head = title.split(": ", 1)[1] if ": " in title[:60] else title
    parts = _SPLIT.split(head, maxsplit=1)
    return parts[0] if len(parts) == 2 else title


def match_posts(
    items: list[dict], source: str, patterns: dict[str, re.Pattern], now: datetime, max_age_days: int
) -> list[dict]:
    """Posts that mention a home airport, newer than max_age_days."""
    cutoff = now - timedelta(days=max_age_days)
    out = []
    for item in items:
        if item["published"] and item["published"] < cutoff:
            continue
        title = item["title"]
        departure = departure_part(title)
        codes = [code for code, pat in patterns.items() if pat.search(departure)]
        if not codes:
            continue
        price = PRICE.search(title)
        out.append(
            {
                "source": source,
                "title": title,
                "url": item["url"],
                "published": item["published"].isoformat() if item["published"] else None,
                "origins": codes,
                "price_text": price.group(0) if price else None,
                "error_fare": bool(ERROR_FARE.search(title)),
            }
        )
    return out


def source_name(url: str) -> str:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    names = {"theflightdeal.com": "The Flight Deal", "reddit.com": "r/flightdeals", "fly4free.com": "Fly4free"}
    return names.get(host, host)


def collect_posts(urls: list[str], origins: dict[str, list[str]], now: datetime, max_age_days: int) -> list[dict]:
    patterns = origin_patterns(origins)
    posts: dict[str, dict] = {}
    for url in urls:
        items = fetch_feed(url)
        matched = match_posts(items, source_name(url), patterns, now, max_age_days)
        log.info("feed %s: %d items, %d from home airports", source_name(url), len(items), len(matched))
        for p in matched:
            posts.setdefault(p["url"], p)
    return sorted(posts.values(), key=lambda p: p["published"] or "", reverse=True)
