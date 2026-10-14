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
from datetime import timedelta
from pathlib import Path

from . import config as config_mod
from .detect import find_deals
from .email_digest import build_digest, email_configured, send_email
from .export import deal_to_json, history_window_start, month_range, write_deals_json
from .notify import format_deal, send_telegram, telegram_configured
from .store import Store, utcnow
from .travelpayouts import TravelpayoutsError, cheapest_by_destination, display_name, load_reference
from .verify import check_live, google_flights_query_url, trip_key

log = logging.getLogger("farescout")
ROOT = Path(__file__).resolve().parent.parent


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

    # 1. Scan: cheapest roundtrip to every destination, per origin and departure month.
    fares: dict[tuple[str, str, str], dict] = {}
    failures = 0
    for origin in cfg.origins:
        for month in months:
            try:
                rows = cheapest_by_destination(origin.code, month, origin.currency, origin.market, token)
            except TravelpayoutsError as e:
                failures += 1
                log.warning("%s", e)
                continue
            for row in rows:
                key = (origin.code, row["destination"], month)
                fares[key] = row
                store.record(today, origin.code, row["destination"], month, row["price"], origin.currency)
            log.info("%s %s: %d destinations", origin.code, month, len(rows))
            time.sleep(cfg.request_delay)
    store.db.commit()
    if not fares:
        log.error("No fares returned (%d failed requests). Check the token and origin codes.", failures)
        store.close()
        return 1

    # 2. Detect deals against each route's baseline.
    def history(o, d, m, cur, since, before):
        return store.history(o, d, m, cur, since, before)

    deals = find_deals(fares, currencies, history, cfg.deals, today)
    log.info("%d fares scanned, %d deals", len(fares), len(deals))

    # 3. Live-check the best deals on Google Flights.
    verifications: dict[str, dict] = {}
    checks = 0
    for deal in deals:
        key = trip_key(deal)
        cached = store.get_verification(key, cfg.verify.cache_hours)
        if cached:
            verifications[key] = cached
            continue
        if args.no_verify or not cfg.verify.enabled or checks >= cfg.verify.max_per_run:
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
    store.db.commit()

    # 4. Export for the dashboard.
    since = history_window_start(today, cfg.deals.history_days)
    out_deals = []
    for deal in deals:
        v = verifications.get(trip_key(deal))
        url = (v or {}).get("url") or google_flights_query_url(deal)
        hist = store.history(deal.origin, deal.destination, deal.month, deal.currency, since)
        out_deals.append(deal_to_json(deal, ref, v, url, hist))
    origins_json = [
        {
            "code": o.code,
            "name": display_name(ref["cities"].get(o.code) or ref["airports"].get(o.code), o.code),
            "currency": o.currency,
        }
        for o in cfg.origins
    ]
    stats = {"fares": len(fares), "months": months, "failed_requests": failures, "live_checks": checks}
    write_deals_json(Path(args.out), now.isoformat(), origins_json, out_deals, stats)
    log.info("wrote %s", args.out)

    # 5. Alerts: one email digest per run, plus a Telegram message per deal if configured.
    if not args.no_alerts and (email_configured() or telegram_configured()):
        fresh = select_new_alerts(out_deals, cfg.alerts, store.last_alert, now)
        delivered = False
        if fresh and email_configured():
            delivered = send_email(*build_digest(fresh, cfg.alerts.dashboard_url)) or delivered
        if fresh and telegram_configured():
            for d in fresh:
                delivered = send_telegram(format_deal(d)) or delivered
        if delivered:
            for d in fresh:
                store.mark_alerted(d["origin"], d["destination"], d["month"], d["price"])
        log.info("%d new deal(s) to alert, delivered: %s", len(fresh), delivered)

    store.prune(keep_days=max(cfg.deals.history_days, 30) + 7, today=today)
    store.close()
    return 0


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
