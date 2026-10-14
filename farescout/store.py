"""SQLite store for fare history, live checks and sent alerts.

Only the daily low per (origin, destination, departure month) is kept, which is what
the baseline needs and keeps the database small enough to carry between CI runs.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS route_daily (
    origin      TEXT NOT NULL,
    destination TEXT NOT NULL,
    month       TEXT NOT NULL,  -- departure month, YYYY-MM
    day         TEXT NOT NULL,  -- day the price was seen, YYYY-MM-DD (UTC)
    price       REAL NOT NULL,
    currency    TEXT NOT NULL,
    PRIMARY KEY (origin, destination, month, day, currency)
);
CREATE TABLE IF NOT EXISTS verifications (
    trip_key   TEXT PRIMARY KEY,  -- origin|destination|depart|return|currency
    checked_at TEXT NOT NULL,
    status     TEXT NOT NULL,     -- confirmed | higher | gone | error | unchecked
    live_price REAL,
    url        TEXT
);
CREATE TABLE IF NOT EXISTS alerts (
    origin      TEXT NOT NULL,
    destination TEXT NOT NULL,
    month       TEXT NOT NULL,
    price       REAL NOT NULL,
    sent_at     TEXT NOT NULL,
    PRIMARY KEY (origin, destination, month)
);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


class Store:
    def __init__(self, path: str | Path):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path))
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.commit()
        self.db.close()

    # --- fare history -------------------------------------------------------

    def record(self, day: date, origin: str, destination: str, month: str, price: float, currency: str) -> None:
        self.db.execute(
            """
            INSERT INTO route_daily (origin, destination, month, day, price, currency)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (origin, destination, month, day, currency)
            DO UPDATE SET price = MIN(price, excluded.price)
            """,
            (origin, destination, month, day.isoformat(), float(price), currency),
        )

    def history(
        self, origin: str, destination: str, month: str, currency: str, since: date, before: date | None = None
    ) -> list[tuple[str, float]]:
        """Daily lows for one route and departure month, oldest first."""
        sql = "SELECT day, price FROM route_daily WHERE origin=? AND destination=? AND month=? AND currency=? AND day>=?"
        args: list = [origin, destination, month, currency, since.isoformat()]
        if before is not None:
            sql += " AND day<?"
            args.append(before.isoformat())
        return [(d, p) for d, p in self.db.execute(sql + " ORDER BY day", args)]

    def prune(self, keep_days: int, today: date) -> int:
        cutoff = (today - timedelta(days=keep_days)).isoformat()
        past_month = today.strftime("%Y-%m")
        cur = self.db.execute("DELETE FROM route_daily WHERE day < ? OR month < ?", (cutoff, past_month))
        self.db.execute("DELETE FROM verifications WHERE checked_at < ?", (cutoff,))
        return cur.rowcount

    # --- live checks --------------------------------------------------------

    def get_verification(self, trip_key: str, max_age_hours: float) -> dict | None:
        row = self.db.execute(
            "SELECT checked_at, status, live_price, url FROM verifications WHERE trip_key=?", (trip_key,)
        ).fetchone()
        if not row:
            return None
        checked_at = datetime.fromisoformat(row[0])
        if utcnow() - checked_at > timedelta(hours=max_age_hours):
            return None
        return {"checked_at": row[0], "status": row[1], "live_price": row[2], "url": row[3]}

    def put_verification(self, trip_key: str, status: str, live_price: float | None, url: str | None) -> dict:
        checked_at = utcnow().isoformat()
        self.db.execute(
            "INSERT OR REPLACE INTO verifications (trip_key, checked_at, status, live_price, url) VALUES (?, ?, ?, ?, ?)",
            (trip_key, checked_at, status, live_price, url),
        )
        return {"checked_at": checked_at, "status": status, "live_price": live_price, "url": url}

    # --- alerts -------------------------------------------------------------

    def last_alert(self, origin: str, destination: str, month: str) -> tuple[float, datetime] | None:
        row = self.db.execute(
            "SELECT price, sent_at FROM alerts WHERE origin=? AND destination=? AND month=?",
            (origin, destination, month),
        ).fetchone()
        return (row[0], datetime.fromisoformat(row[1])) if row else None

    def mark_alerted(self, origin: str, destination: str, month: str, price: float) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO alerts (origin, destination, month, price, sent_at) VALUES (?, ?, ?, ?, ?)",
            (origin, destination, month, float(price), utcnow().isoformat()),
        )
