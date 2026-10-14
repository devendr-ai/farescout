"""Email digest of new deals, sent over SMTP.

Configure with environment variables (GitHub secrets in CI):
    SMTP_USER       login, e.g. you@gmail.com
    SMTP_PASSWORD   password; for Gmail, an app password
    ALERT_EMAIL_TO  recipient(s), comma-separated (default: SMTP_USER)
    SMTP_HOST       default smtp.gmail.com
    SMTP_PORT       default 465 (SSL); 587 uses STARTTLS
"""

from __future__ import annotations

import html
import logging
import os
import smtplib
import ssl
from datetime import date
from email.message import EmailMessage

log = logging.getLogger(__name__)


def email_configured() -> bool:
    return bool(os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASSWORD"))


def _day(iso: str) -> str:
    try:
        d = date.fromisoformat(iso)
    except (TypeError, ValueError):
        return iso or "?"
    return f"{d:%a}, {d:%b} {d.day}"


def _stops(n: int | None) -> str:
    if n is None:
        return "stops unknown"
    return "nonstop" if n == 0 else f"{n} stop" + ("s" if n > 1 else "")


def _check_text(d: dict) -> str:
    v = d.get("verified") or {}
    if v.get("status") == "confirmed":
        return f"Live-checked on Google Flights: {d.get('price_label_live')}"
    return "Not live-checked"


def build_digest(deals: list[dict], dashboard_url: str = "") -> tuple[str, str, str]:
    """Return (subject, plain text, html) for a digest of `deals`, best first."""
    deals = sorted(deals, key=lambda d: d["off"], reverse=True)
    best = deals[0]
    n = len(deals)
    subject = (
        f"{n} flight deal{'s' if n > 1 else ''}: "
        f"{best['origin']} to {best['destination_name']} {best['price_label']} ({round(best['off'] * 100)}% off)"
    )
    if n > 1:
        subject += f" + {n - 1} more"

    text_lines = []
    for d in deals:
        mistake = "POSSIBLE MISTAKE FARE. " if d["mistake"] else ""
        text_lines += [
            f"{d['origin_name']} ({d['origin']}) to {d['destination_name']}, {d['country_name']}",
            f"  {mistake}{d['price_label']} roundtrip, {round(d['off'] * 100)}% below typical {d['baseline_label']}",
            f"  {_day(d['depart_date'])} to {_day(d['return_date'])} · {d['airline_name']} · {_stops(d.get('transfers'))}",
            f"  {_check_text(d)}",
            f"  Google Flights: {d['google_url']}",
            "",
        ]
    if dashboard_url:
        text_lines.append(f"All deals: {dashboard_url}")
    text = "\n".join(text_lines)

    e = html.escape
    rows = []
    for d in deals:
        color = "#B9410E" if d["mistake"] else "#0B7F57"
        tag = (
            '<span style="background:#FBE6DA;color:#B9410E;font-size:11px;font-weight:700;'
            'padding:2px 6px;border-radius:4px;text-transform:uppercase">Possible mistake fare</span> '
            if d["mistake"]
            else ""
        )
        links = f'<a href="{e(d["google_url"])}" style="color:#1C4BD6">Google Flights</a>'
        if d.get("aviasales_url"):
            links += f' · <a href="{e(d["aviasales_url"])}" style="color:#1C4BD6">Aviasales</a>'
        rows.append(
            f"""<tr><td style="padding:14px 0;border-bottom:1px solid #D3DCE6">
  <div style="font:700 12px/1 Arial,sans-serif;letter-spacing:.05em">
    <span style="background:#15181D;color:#FFC72C;padding:4px 6px;border-radius:3px 0 0 3px">{e(d['origin'])}</span><span style="background:#FFC72C;color:#15181D;padding:4px 6px;border-radius:0 3px 3px 0">→ {e(d['destination'])}</span>
  </div>
  <div style="font:700 18px/1.3 Arial,sans-serif;margin-top:8px">{e(d['destination_name'])} <span style="font-weight:400;font-size:13px;color:#56667A">{e(d['country_name'])}</span></div>
  <div style="margin-top:2px">{tag}<span style="font:800 22px Arial,sans-serif;color:{color}">{e(d['price_label'])}</span>
    <span style="font-size:13px;color:#56667A">roundtrip · {round(d['off'] * 100)}% below typical <s>{e(d['baseline_label'])}</s></span></div>
  <div style="font-size:13px;margin-top:4px">{e(_day(d['depart_date']))} → {e(_day(d['return_date']))} · {e(d['airline_name'])} · {e(_stops(d.get('transfers')))}</div>
  <div style="font-size:12px;color:#56667A;margin-top:2px">{e(_check_text(d))}</div>
  <div style="font-size:13px;margin-top:6px">{links}</div>
</td></tr>"""
        )
    footer = (
        f'<p style="font-size:13px"><a href="{e(dashboard_url)}" style="color:#1C4BD6">See all deals on the dashboard</a></p>'
        if dashboard_url
        else ""
    )
    body_html = f"""<!doctype html><html><body style="margin:0;padding:16px;background:#ffffff;color:#0E1A2B;font-family:Arial,sans-serif">
<div style="max-width:560px;margin:0 auto">
<h1 style="font-size:20px;margin:0 0 4px">New flight deals</h1>
<p style="font-size:13px;color:#56667A;margin:0">Fares far below each route's normal price. Cached prices can move fast; book soon if one fits.</p>
<table role="presentation" style="width:100%;border-collapse:collapse;margin-top:8px">{''.join(rows)}</table>
{footer}
</div></body></html>"""
    return subject, text, body_html


def send_email(subject: str, text: str, body_html: str) -> bool:
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    if not user or not password:
        return False
    host = os.environ.get("SMTP_HOST") or "smtp.gmail.com"
    port = int(os.environ.get("SMTP_PORT") or 465)
    to = [a.strip() for a in (os.environ.get("ALERT_EMAIL_TO") or user).split(",") if a.strip()]

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"Farescout <{user}>"
    msg["To"] = ", ".join(to)
    msg.set_content(text)
    msg.add_alternative(body_html, subtype="html")

    context = ssl.create_default_context()
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as s:
                s.login(user, password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.starttls(context=context)
                s.login(user, password)
                s.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        # Never log credentials; the exception text from smtplib doesn't include them.
        log.warning("email send failed: %s", e)
        return False
    return True
