"""Load and validate config.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Origin:
    code: str
    currency: str
    market: str


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
    max_per_run: int = 15
    delay_seconds: float = 4.0
    tolerance: float = 0.15
    cache_hours: int = 12


@dataclass(frozen=True)
class AlertRules:
    min_off: float = 0.50
    realert_drop: float = 0.10
    realert_days: int = 14


@dataclass(frozen=True)
class Config:
    origins: list[Origin]
    months_ahead: int = 10
    request_delay: float = 0.4
    deals: DealRules = field(default_factory=DealRules)
    verify: VerifyRules = field(default_factory=VerifyRules)
    alerts: AlertRules = field(default_factory=AlertRules)


def load(path: str | Path) -> Config:
    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    origins = [
        Origin(
            code=o["code"].strip().upper(),
            currency=o.get("currency", "usd").strip().lower(),
            market=o.get("market", "us").strip().lower(),
        )
        for o in raw.get("origin", [])
    ]
    if not origins:
        raise ValueError(f"{path}: add at least one [[origin]] block")
    for o in origins:
        if len(o.code) != 3 or not o.code.isalpha():
            raise ValueError(f"{path}: origin code {o.code!r} must be a 3-letter IATA code")

    scan = raw.get("scan", {})
    deals = DealRules(**raw.get("deals", {}))
    if not 0 < deals.min_off <= deals.mistake_off < 1:
        raise ValueError(f"{path}: need 0 < deals.min_off <= deals.mistake_off < 1")
    return Config(
        origins=origins,
        months_ahead=int(scan.get("months_ahead", 10)),
        request_delay=float(scan.get("request_delay", 0.4)),
        deals=deals,
        verify=VerifyRules(**raw.get("verify", {})),
        alerts=AlertRules(**raw.get("alerts", {})),
    )
