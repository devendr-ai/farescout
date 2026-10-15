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
        text = f"Live-checked on Google Flights: {d.get('price_label_live')}"
        if d.get("google_typical_label"):
            text += f". Google says this trip usually costs {d['google_typical_label']}"
        return text
    return "Not live-checked"


def _subject(deals: list[dict], posts: list[dict], urgent: bool) -> str:
    if deals:
        best = deals[0]
        lead = f"{best['origin']} to {best['destination_name']} {best['price_label']} ({round(best['off'] * 100)}% off)"
        if urgent:
            subject = f"Possible mistake fare: {lead}"
        else:
            subject = f"{len(deals)} flight deal{'s' if len(deals) > 1 else ''}: {lead}"
        more = len(deals) - 1 + len(posts)
        return subject + (f" + {more} more" if more else "")
    first = posts[0]
    prefix = "Error fare" if urgent else f"{len(posts)} new deal post{'s' if len(posts) > 1 else ''}"
    title = first["title"] if len(first["title"]) <= 90 else first["title"][:87] + "..."
    return f"{prefix}: {title}"


def build_digest(
    deals: list[dict], posts: list[dict] | tuple = (), dashboard_url: str = "", urgent: bool = False
) -> tuple[str, str, str]:
    """Return (subject, plain text, html) for deals (best first) and deal-site posts.

    urgent=True is the instant email for mistake fares sent between digests.
    """
    deals = sorted(deals, key=lambda d: d["off"], reverse=True)
    posts = list(posts)
    if not deals and not posts:
        raise ValueError("nothing to send")
    subject = _subject(deals, posts, urgent)
    e = html.escape

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
    if posts:
        text_lines.append("From deal sites:")
        for p in posts:
            flag = "ERROR FARE. " if p["error_fare"] else ""
            text_lines += [f"  {flag}{p['title']} ({p['source']})", f"  {p['url']}", ""]
    if dashboard_url:
        text_lines.append(f"All deals: {dashboard_url}")
    text = "\n".join(text_lines)

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
    post_rows = []
    for p in posts:
        tag = (
            '<span style="background:#FBE6DA;color:#B9410E;font-size:11px;font-weight:700;'
            'padding:2px 6px;border-radius:4px;text-transform:uppercase">Error fare</span> '
            if p["error_fare"]
            else ""
        )
        post_rows.append(
            f"""<tr><td style="padding:10px 0;border-bottom:1px solid #D3DCE6;font-size:14px">
  {tag}<a href="{e(p['url'])}" style="color:#0E1A2B;font-weight:700;text-decoration:none">{e(p['title'])}</a>
  <div style="font-size:12px;color:#56667A;margin-top:2px">{e(p['source'])}</div>
</td></tr>"""
        )
    posts_html = (
        '<h2 style="font-size:16px;margin:20px 0 0">From deal sites</h2>'
        f'<table role="presentation" style="width:100%;border-collapse:collapse">{"".join(post_rows)}</table>'
        if post_rows
        else ""
    )
    deals_html = (
        f'<table role="presentation" style="width:100%;border-collapse:collapse;margin-top:8px">{"".join(rows)}</table>'
        if rows
        else ""
    )
    heading = "Possible mistake fare" if urgent else "New flight deals"
    footer = (
        f'<p style="font-size:13px"><a href="{e(dashboard_url)}" style="color:#1C4BD6">See all deals on the dashboard</a></p>'
        if dashboard_url
        else ""
    )
    body_html = f"""<!doctype html><html><body style="margin:0;padding:16px;background:#ffffff;color:#0E1A2B;font-family:Arial,sans-serif">
<div style="max-width:560px;margin:0 auto">
<h1 style="font-size:20px;margin:0 0 4px">{heading}</h1>
<p style="font-size:13px;color:#56667A;margin:0">Fares far below each route's normal price. Prices move fast; book soon if one fits.</p>
{deals_html}
{posts_html}
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
