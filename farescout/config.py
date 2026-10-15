"""Load and validate config.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Origin:
    code: str
    currency: str
    # Aviasales data markets to pull from. Each market is a different pool of user searches.
    markets: tuple[str, ...]


@dataclass(frozen=True)
class DealRules:
    min_off: float = 0.40
    mistake_off: float = 0.65
    history_days: int = 90
    min_history_days: int = 7
    min_other_months: int = 4


@dataclass(frozen=True)
class VerifyRules:
    enabled: bool = True
    max_per_run: int = 12
    delay_seconds: float = 4.0
    tolerance: float = 0.15
    cache_hours: int = 6


@dataclass(frozen=True)
class SerpApiRules:
    # Live checks for possible mistake fares through SerpApi (needs SERPAPI_API_KEY).
    enabled: bool = True
    monthly_budget: int = 240  # free plan: 250
    daily_budget: int = 8
    max_per_run: int = 3
    # Don't re-check the same trip within this many hours.
    cache_hours: int = 24


@dataclass(frozen=True)
class AlertRules:
    min_off: float = 0.50
    require_live_check: bool = True
    realert_drop: float = 0.10
    realert_days: int = 14
    dashboard_url: str = ""
    # UTC hours at which the regular digest goes out (the first scan at or after each hour).
    digest_hours_utc: tuple[int, ...] = (1, 13)
    # Email right away, outside the digest, for confirmed mistake fares and error-fare posts.
    instant_mistake_fares: bool = True


@dataclass(frozen=True)
class FeedRules:
    enabled: bool = True
    urls: tuple[str, ...] = ()
    max_age_days: int = 3


@dataclass(frozen=True)
class Config:
    origins: list[Origin]
    months_ahead: int = 10
    request_delay: float = 0.4
    nonstop_scan: bool = True
    special_offers: bool = True
    deals: DealRules = field(default_factory=DealRules)
    verify: VerifyRules = field(default_factory=VerifyRules)
    serpapi: SerpApiRules = field(default_factory=SerpApiRules)
    alerts: AlertRules = field(default_factory=AlertRules)
    feeds: FeedRules = field(default_factory=FeedRules)


def load(path: str | Path) -> Config:
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    origins = []
    for o in raw.get("origin", []):
        markets = o.get("markets") or [o.get("market", "us")]
        origins.append(
            Origin(
                code=o["code"].strip().upper(),
                currency=o.get("currency", "usd").strip().lower(),
                markets=tuple(m.strip().lower() for m in markets),
            )
        )
    if not origins:
        raise ValueError(f"{path}: add at least one [[origin]] block")
    for o in origins:
        if len(o.code) != 3 or not o.code.isalpha():
            raise ValueError(f"{path}: origin code {o.code!r} must be a 3-letter IATA code")

    scan = raw.get("scan", {})
    deals = DealRules(**raw.get("deals", {}))
    if not 0 < deals.min_off <= deals.mistake_off < 1:
        raise ValueError(f"{path}: need 0 < deals.min_off <= deals.mistake_off < 1")
    alerts_raw = dict(raw.get("alerts", {}))
    if "digest_hours_utc" in alerts_raw:
        hours = tuple(int(h) for h in alerts_raw["digest_hours_utc"])
        if not hours or any(not 0 <= h <= 23 for h in hours):
            raise ValueError(f"{path}: alerts.digest_hours_utc needs hours between 0 and 23")
        alerts_raw["digest_hours_utc"] = hours
    feeds_raw = dict(raw.get("feeds", {}))
    feeds_raw["urls"] = tuple(feeds_raw.get("urls", ()))
    return Config(
        origins=origins,
        months_ahead=int(scan.get("months_ahead", 10)),
        request_delay=float(scan.get("request_delay", 0.4)),
        nonstop_scan=bool(scan.get("nonstop_scan", True)),
        special_offers=bool(scan.get("special_offers", True)),
        deals=deals,
        verify=VerifyRules(**raw.get("verify", {})),
        serpapi=SerpApiRules(**raw.get("serpapi", {})),
        alerts=AlertRules(**alerts_raw),
        feeds=FeedRules(**feeds_raw),
    )
