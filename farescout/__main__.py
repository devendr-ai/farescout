"""Command line entry point.

    python -m farescout scan          # scan, detect, live-check, write docs/deals.json, alert
    python -m farescout scan --no-verify --no-alerts
    python -m farescout test-alert    # send a test email and/or Telegram message
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from . import config as config_mod
from . import serpapi
from .detect import find_deals
from .email_digest import build_digest, email_configured, send_email
from .export import deal_to_json, history_window_start, month_range, write_deals_json
from .feeds import collect_posts
from .notify import format_deal, format_post, send_telegram, telegram_configured
from .store import Store, utcnow
from .travelpayouts import (
    TravelpayoutsError,
    cheapest_by_destination,
    display_name,
    load_reference,
    special_offers,
)
from .verify import check_live, google_flights_query_url, trip_key

log = logging.getLogger("farescout")
ROOT = Path(__file__).resolve().parent.parent


def scan_fares(cfg, store: Store, token: str, months: list[str], today, direct: bool) -> tuple[dict, int, int]:
    """Cheapest roundtrip per (origin, destination, month) across each origin's markets.

    Returns (fares, requests, failures). Every price seen is recorded in the history.
    """
    fares: dict[tuple[str, str, str], dict] = {}
    requests = failures = 0
    for origin in cfg.origins:
        for market in origin.markets:
            for month in months:
                requests += 1
                try:
                    rows = cheapest_by_destination(origin.code, month, origin.currency, market, token, direct=direct)
                except TravelpayoutsError as e:
                    failures += 1
                    log.warning("%s", e)
                    continue
                for row in rows:
                    _add_fare(fares, store, today, origin, row, month, direct)
                log.debug("%s %s %s%s: %d destinations", origin.code, market, month, " nonstop" if direct else "", len(rows))
                time.sleep(cfg.request_delay)
    return fares, requests, failures


def _add_fare(fares: dict, store: Store, today, origin, row: dict, month: str, direct: bool) -> None:
    key = (origin.code, row["destination"], month)
    if key not in fares or row["price"] < fares[key]["price"]:
        fares[key] = row
    store.record(today, origin.code, row["destination"], month, row["price"], origin.currency, direct=direct)


def digest_due(now, hours_utc: tuple[int, ...], last_sent_iso: str | None) -> bool:
    """True if a digest slot has passed since the last digest (first run at or after each hour)."""
    if last_sent_iso is None:
        return True
    last = datetime.fromisoformat(last_sent_iso)
    slots = [
        (now - timedelta(days=back)).replace(hour=h, minute=0, second=0, microsecond=0)
        for back in (0, 1)
        for h in hours_utc
    ]
    latest = max(t for t in slots if t <= now)
    return last < latest


def verify_deals(cfg, store: Store, deals: list, no_verify: bool, today) -> tuple[dict, int, int]:
    """Live-check deals. Returns (verifications by trip key, fast-flights checks, SerpApi checks)."""
    verifications: dict[str, dict] = {}
    checks = serp_checks = 0
    serp_key = serpapi.api_key() if cfg.serpapi.enabled else None
    serp_left: int | None = None  # fetched once, only if needed
    month, day = today.strftime("%Y-%m"), today.isoformat()
    for deal in deals:
        key = trip_key(deal)
        cache_hours = max(cfg.verify.cache_hours, cfg.serpapi.cache_hours) if deal.mistake else cfg.verify.cache_hours
        cached = store.get_verification(key, cache_hours)
        if cached:
            verifications[key] = cached
            continue
        if no_verify:
            continue
        within_budget = (
            serp_checks < cfg.serpapi.max_per_run
            and store.count_usage("serpapi", month) < cfg.serpapi.monthly_budget
            and store.count_usage("serpapi", day) < cfg.serpapi.daily_budget
        )
        if deal.mistake and serp_key and within_budget:
            if serp_left is None:
                serp_left = serpapi.searches_left(serp_key)
            if serp_left is None or serp_left > 0:
                r = serpapi.check(deal, serp_key, cfg.verify.tolerance)
                serp_checks += 1
                store.add_usage("serpapi", [month, day])
                if serp_left is not None:
                    serp_left -= 1
                log.info("SerpApi check %s-%s %s: %s %s", deal.origin, deal.destination, deal.month, r["status"], r["live_price"] or "")
                if r["status"] in ("confirmed", "higher"):
                    verifications[key] = store.put_verification(
                        key, r["status"], r["live_price"], r["url"], "serpapi",
                        r["price_level"], r["typical_low"], r["typical_high"],
                    )
                    continue
                # SerpApi had no answer: fall back to fast-flights below.
        if not cfg.verify.enabled or checks >= cfg.verify.max_per_run:
            continue
        status, live, url = check_live(deal, cfg.verify.tolerance)
        checks += 1
        if status in ("confirmed", "higher"):
            verifications[key] = store.put_verification(key, status, live, url)
        elif status == "error":
            # Show this run's failure, but don't cache it, so the next run retries.
            verifications[key] = {"checked_at": utcnow().isoformat(), "status": status, "live_price": None, "url": url}
        log.info("live check %s-%s %s: %s %s", deal.origin, deal.destination, deal.month, status, live or "")
        time.sleep(cfg.verify.delay_seconds)
    return verifications, checks, serp_checks


def cmd_scan(args: argparse.Namespace) -> int:
    cfg = config_mod.load(args.config)
    token = os.environ.get("TRAVELPAYOUTS_TOKEN")
    if not token:
        log.error("TRAVELPAYOUTS_TOKEN is not set. Get a token at travelpayouts.com (Profile > API token).")
        return 2

    now = utcnow()
    today = now.date()
    store = Store(args.db)
    ref = load_reference(Path(args.db).parent / "ref")
    months = month_range(today, cfg.months_ahead)
    currencies = {o.code: o.currency for o in cfg.origins}

    # 1. Scan: cheapest roundtrip to every destination, per origin, market and departure month,
    #    plus Aviasales' special offers, plus a separate nonstop-only pass.
    fares, requests, failures = scan_fares(cfg, store, token, months, today, direct=False)
    month_set = set(months)
    if cfg.special_offers:
        for origin in cfg.origins:
            for market in origin.markets:
                requests += 1
                try:
                    offers = special_offers(origin.code, origin.currency, market, token)
                except TravelpayoutsError as e:
                    failures += 1
                    log.warning("%s", e)
                    continue
                for row in offers:
                    month = row["departure_at"][:7]
                    if month in month_set:
                        _add_fare(fares, store, today, origin, row, month, direct=False)
                log.info("%s %s special offers: %d", origin.code, market, len(offers))
    nonstop_fares: dict = {}
    if cfg.nonstop_scan:
        nonstop_fares, n_req, n_fail = scan_fares(cfg, store, token, months, today, direct=True)
        requests += n_req
        failures += n_fail
    store.db.commit()
    log.info("%d requests (%d failed): %d fares, %d nonstop fares", requests, failures, len(fares), len(nonstop_fares))
    if not fares:
        log.error("No fares returned. Check the token and origin codes.")
        store.close()
        return 1

    # 2. Detect deals against each route's baseline. Nonstop fares are compared with nonstop history.
    def history(o, d, m, cur, since, before):
        return store.history(o, d, m, cur, since, before)

    def nonstop_history(o, d, m, cur, since, before):
        return store.history(o, d, m, cur, since, before, direct=True)

    deals = find_deals(fares, currencies, history, cfg.deals, today)
    found = {d.key for d in deals if d.fare.get("transfers") == 0 and d.fare.get("return_transfers") == 0}
    deals += [
        d
        for d in find_deals(nonstop_fares, currencies, nonstop_history, cfg.deals, today, nonstop=True)
        if d.key not in found  # already found as a nonstop deal in the main pass
    ]
    deals.sort(key=lambda d: d.off, reverse=True)
    log.info("%d deals", len(deals))

    # 3. Live-check the best deals: SerpApi for possible mistake fares (budgeted), fast-flights for the rest.
    verifications, checks, serp_checks = verify_deals(cfg, store, deals, args.no_verify, today)
    store.db.commit()

    # 4. Deal-site feeds: posts leaving from a home airport.
    posts: list[dict] = []
    if cfg.feeds.enabled and cfg.feeds.urls:
        names = {o.code: origin_names(ref, o.code) for o in cfg.origins}
        posts = collect_posts(list(cfg.feeds.urls), names, now, cfg.feeds.max_age_days)

    # 5. Export for the dashboard.
    since = history_window_start(today, cfg.deals.history_days)
    out_deals = []
    for deal in deals:
        v = verifications.get(trip_key(deal))
        url = (v or {}).get("url") or google_flights_query_url(deal)
        hist = store.history(deal.origin, deal.destination, deal.month, deal.currency, since, direct=deal.nonstop)
        out_deals.append(deal_to_json(deal, ref, v, url, hist))
    origins_json = [
        {
            "code": o.code,
            "name": display_name(ref["cities"].get(o.code) or ref["airports"].get(o.code), o.code),
            "currency": o.currency,
        }
        for o in cfg.origins
    ]
    stats = {
        "fares": len(fares),
        "nonstop_fares": len(nonstop_fares),
        "requests": requests,
        "months": months,
        "failed_requests": failures,
        "live_checks": checks + serp_checks,
        "serpapi_checks": serp_checks,
        "posts": len(posts),
    }
    write_deals_json(Path(args.out), now.isoformat(), origins_json, out_deals, stats, posts)
    log.info("wrote %s", args.out)

    # 6. Alerts. A digest goes out at the configured hours; confirmed mistake fares and
    #    error-fare posts go out right away.
    if not args.no_alerts and (email_configured() or telegram_configured()):
        send_alerts(cfg, store, out_deals, posts, now)

    store.prune(keep_days=max(cfg.deals.history_days, 30) + 7, today=today)
    store.close()
    return 0


def origin_names(ref: dict, code: str) -> list[str]:
    """Names a deal site might use for a home airport: its city, plus the airport's city."""
    place = ref["cities"].get(code) or ref["airports"].get(code) or {}
    names = {display_name(place, "")}
    city_code = place.get("city_code")
    if city_code:
        names.add(display_name(ref["cities"].get(city_code), ""))
    return sorted(n for n in names if n)


def send_alerts(cfg, store: Store, out_deals: list[dict], posts: list[dict], now) -> None:
    fresh_deals = select_new_alerts(out_deals, cfg.alerts, store.last_alert, now)
    fresh_posts = [p for p in posts if not store.post_seen(p["url"])]
    digest = digest_due(now, cfg.alerts.digest_hours_utc, store.get_meta("last_digest_at"))
    if not digest:
        if not cfg.alerts.instant_mistake_fares:
            return
        fresh_deals = [d for d in fresh_deals if d["mistake"]]
        fresh_posts = [p for p in fresh_posts if p["error_fare"]]
    if fresh_deals or fresh_posts:
        delivered = False
        if email_configured():
            subject, text, body = build_digest(fresh_deals, fresh_posts, cfg.alerts.dashboard_url, urgent=not digest)
            delivered = send_email(subject, text, body) or delivered
        if telegram_configured():
            for d in fresh_deals:
                delivered = send_telegram(format_deal(d)) or delivered
            for p in fresh_posts:
                delivered = send_telegram(format_post(p)) or delivered
        if delivered:
            for d in fresh_deals:
                store.mark_alerted(d["origin"], d["destination"], d["month"], d["price"])
            for p in fresh_posts:
                store.mark_post_seen(p["url"])
        log.info(
            "%s: %d deal(s), %d post(s), delivered: %s",
            "digest" if digest else "instant alert", len(fresh_deals), len(fresh_posts), delivered,
        )
    if digest:
        store.set_meta("last_digest_at", now.isoformat())


def select_new_alerts(deals: list[dict], rules, last_alert, now) -> list[dict]:
    """Deals worth alerting that haven't been sent, or got cheaper since they were."""
    out = []
    for d in deals:
        status = d["verified"]["status"]
        if d["off"] < rules.min_off or status in ("gone", "higher"):
            continue
        if rules.require_live_check and status != "confirmed":
            continue
        last = last_alert(d["origin"], d["destination"], d["month"])
        if last:
            last_price, sent_at = last
            dropped = d["price"] <= last_price * (1 - rules.realert_drop)
            stale = now - sent_at > timedelta(days=rules.realert_days)
            if not (dropped or stale):
                continue
        out.append(d)
    return out


def cmd_test_alert(args: argparse.Namespace) -> int:
    if not (email_configured() or telegram_configured()):
        log.error("Set SMTP_USER and SMTP_PASSWORD (email) or TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID first.")
        return 2
    ok = True
    if email_configured():
        sent = send_email(
            "Farescout test email",
            "Farescout is set up. Deal digests will arrive at this address.",
            "<p>Farescout is set up. Deal digests will arrive at this address.</p>",
        )
        log.info("email sent" if sent else "email failed. Check SMTP_USER, SMTP_PASSWORD and the app password.")
        ok = ok and sent
    if telegram_configured():
        sent = send_telegram("✈️ Farescout test alert. Deals will arrive here.")
        log.info("Telegram sent" if sent else "Telegram rejected the message. Check the token and chat id.")
        ok = ok and sent
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="farescout")
    parser.add_argument("--config", default=str(ROOT / "config.toml"))
    parser.add_argument("--db", default=str(ROOT / "data" / "farescout.db"))
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan", help="scan fares, find deals, write deals.json, send alerts")
    scan.add_argument("--out", default=str(ROOT / "docs" / "deals.json"))
    scan.add_argument("--no-verify", action="store_true", help="skip Google Flights live checks")
    scan.add_argument("--no-alerts", action="store_true", help="skip email and Telegram alerts")
    scan.set_defaults(func=cmd_scan)
    test = sub.add_parser("test-alert", help="send a test email and/or Telegram message")
    test.set_defaults(func=cmd_test_alert)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
