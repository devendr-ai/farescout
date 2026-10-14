"""Telegram alerts. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to enable."""

from __future__ import annotations

import html
import json
import logging
import os
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)


def telegram_configured() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


def send_telegram(text_html: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False
    body = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": text_html, "parse_mode": "HTML", "disable_web_page_preview": "true"}
    ).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            ok = json.load(resp).get("ok", False)
    except Exception as e:
        # Don't log the URL: it contains the bot token.
        log.warning("Telegram send failed: %s", type(e).__name__)
        return False
    return bool(ok)


def format_deal(d: dict) -> str:
    """One deal from deals.json as a Telegram HTML message."""
    e = html.escape
    flag = "🚨 Possible mistake fare" if d["mistake"] else "✈️ Fare deal"
    live = d.get("verified") or {}
    if live.get("status") == "confirmed":
        check = f"Live-checked on Google Flights: {e(d['price_label_live'])}"
    elif live.get("status") == "higher":
        check = f"Google Flights shows {e(d['price_label_live'])} now"
    else:
        check = "Not live-checked yet"
    stops = "nonstop" if not d.get("transfers") else f"{d['transfers']} stop" + ("s" if d["transfers"] > 1 else "")
    lines = [
        f"<b>{flag}: {e(d['origin_name'])} → {e(d['destination_name'])}</b>",
        f"<b>{e(d['price_label'])}</b> roundtrip, {round(d['off'] * 100)}% below typical {e(d['baseline_label'])}",
        f"{e(d['depart_date'])} → {e(d['return_date'])} · {e(d['airline_name'])} · {stops}",
        check,
    ]
    links = []
    if d.get("google_url"):
        links.append(f'<a href="{e(d["google_url"])}">Google Flights</a>')
    if d.get("aviasales_url"):
        links.append(f'<a href="{e(d["aviasales_url"])}">Aviasales</a>')
    if links:
        lines.append(" · ".join(links))
    return "\n".join(lines)
