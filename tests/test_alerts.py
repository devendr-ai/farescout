import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from farescout.__main__ import select_new_alerts
from farescout.config import AlertRules
from farescout.email_digest import build_digest, send_email

NOW = datetime(2026, 10, 14, 14, 0, tzinfo=timezone.utc)


def deal(dest="NRT", off=0.6, status="confirmed", price=480.0, mistake=False, name="Tokyo"):
    return {
        "id": f"SEA-{dest}-2027-02", "origin": "SEA", "origin_name": "Seattle", "destination": dest,
        "destination_name": name, "country_name": "Japan", "month": "2027-02", "price": price,
        "price_label": f"${price:.0f}", "baseline_label": "$1,200", "off": off, "mistake": mistake,
        "airline_name": "ANA", "transfers": 0, "depart_date": "2027-02-11", "return_date": "2027-02-21",
        "google_url": "https://www.google.com/travel/flights/search?tfs=abc&hl=en-US",
        "aviasales_url": None, "verified": {"status": status, "live_price": price}, "price_label_live": f"${price:.0f}",
    }


def never_alerted(*_):
    return None


class SelectAlertsTests(unittest.TestCase):
    def test_only_confirmed_big_drops_by_default(self):
        deals = [deal("NRT"), deal("ICN", status="unchecked"), deal("LIS", off=0.45), deal("CUN", status="higher")]
        picked = select_new_alerts(deals, AlertRules(), never_alerted, NOW)
        self.assertEqual([d["destination"] for d in picked], ["NRT"])

    def test_unchecked_allowed_when_live_check_not_required(self):
        deals = [deal("NRT"), deal("ICN", status="unchecked"), deal("BKK", status="error")]
        picked = select_new_alerts(deals, AlertRules(require_live_check=False), never_alerted, NOW)
        self.assertEqual([d["destination"] for d in picked], ["NRT", "ICN", "BKK"])

    def test_no_repeat_unless_cheaper_or_old(self):
        rules = AlertRules()
        recent = lambda *_: (480.0, NOW - timedelta(days=1))
        self.assertEqual(select_new_alerts([deal()], rules, recent, NOW), [])
        self.assertEqual(len(select_new_alerts([deal(price=420.0)], rules, recent, NOW)), 1)
        old = lambda *_: (480.0, NOW - timedelta(days=15))
        self.assertEqual(len(select_new_alerts([deal()], rules, old, NOW)), 1)


class DigestTests(unittest.TestCase):
    def test_subject_names_best_deal_and_count(self):
        subject, text, body = build_digest([deal("ICN", off=0.52, name="Seoul"), deal("NRT", off=0.61)], "https://x.test/")
        self.assertEqual(subject, "2 flight deals: SEA to Tokyo $480 (61% off) + 1 more")
        self.assertLess(text.index("Tokyo"), text.index("Seoul"))
        self.assertIn("Thu, Feb 11 to Sun, Feb 21", text)
        self.assertIn("https://x.test/", body)

    def test_html_escapes_untrusted_names(self):
        _, _, body = build_digest([deal(name="<script>x</script>")])
        self.assertNotIn("<script>x", body)
        self.assertIn("&lt;script&gt;", body)

    def test_mistake_fare_flagged(self):
        _, text, body = build_digest([deal(off=0.7, mistake=True)])
        self.assertIn("POSSIBLE MISTAKE FARE", text)
        self.assertIn("Possible mistake fare", body)


class SendEmailTests(unittest.TestCase):
    ENV = {"SMTP_USER": "me@example.com", "SMTP_PASSWORD": "app-password", "ALERT_EMAIL_TO": "", "SMTP_HOST": "", "SMTP_PORT": ""}

    def test_sends_multipart_message_over_ssl_with_defaults(self):
        with mock.patch.dict(os.environ, self.ENV), mock.patch("smtplib.SMTP_SSL") as smtp:
            ok = send_email(*build_digest([deal()]))
        self.assertTrue(ok)
        smtp.assert_called_once()
        self.assertEqual(smtp.call_args.args[:2], ("smtp.gmail.com", 465))
        conn = smtp.return_value.__enter__.return_value
        conn.login.assert_called_once_with("me@example.com", "app-password")
        msg = conn.send_message.call_args.args[0]
        self.assertEqual(msg["To"], "me@example.com")
        self.assertEqual([p.get_content_type() for p in msg.iter_parts()], ["text/plain", "text/html"])

    def test_not_configured_sends_nothing(self):
        with mock.patch.dict(os.environ, {"SMTP_USER": "", "SMTP_PASSWORD": ""}), mock.patch("smtplib.SMTP_SSL") as smtp:
            self.assertFalse(send_email("s", "t", "<p>h</p>"))
        smtp.assert_not_called()


if __name__ == "__main__":
    unittest.main()
