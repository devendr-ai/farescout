import unittest
from datetime import datetime, timezone
from unittest import mock

from farescout import travelpayouts
from farescout.__main__ import digest_due
from farescout.feeds import departure_part, match_posts, origin_patterns, parse_feed

NOW = datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc)
HOME = origin_patterns({"SEA": ["Seattle"], "SFO": ["San Francisco"], "PDX": ["Portland"], "DEL": ["Delhi", "New Delhi"]})

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>United: Seattle &#8211; Reykjavik, Iceland. $492 (Basic Economy). Roundtrip</title>
  <link>https://www.theflightdeal.com/a</link><pubDate>Wed, 14 Oct 2026 09:00:00 +0000</pubDate></item>
<item><title>Delta: New York &#8211; Seattle. $198 Roundtrip</title>
  <link>https://www.theflightdeal.com/b</link><pubDate>Wed, 14 Oct 2026 08:00:00 +0000</pubDate></item>
<item><title>Error fare: San Francisco to Tokyo $310 roundtrip</title>
  <link>https://www.theflightdeal.com/c</link><pubDate>Tue, 13 Oct 2026 20:00:00 +0000</pubDate></item>
<item><title>Cheap flights from Portland to Rome for $520</title>
  <link>https://www.theflightdeal.com/d</link><pubDate>Fri, 02 Oct 2026 20:00:00 +0000</pubDate></item>
</channel></rss>"""

ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>[DEL] New Delhi to Bangkok \xe2\x82\xb99,800 roundtrip</title><link href="https://www.reddit.com/r/flightdeals/x"/>
  <updated>2026-10-14T10:00:00+00:00</updated></entry>
</feed>"""


class FeedTests(unittest.TestCase):
    def test_departure_part(self):
        self.assertEqual(departure_part("Delta: San Francisco – Porto, Portugal. $711"), "San Francisco")
        self.assertEqual(departure_part("Cheap flights from Brussels to Los Angeles for €384"), "Brussels")
        self.assertEqual(departure_part("Business Class Deal: Brussels to Hong Kong 1720€"), "Brussels")

    def test_rss_matches_departures_only_and_recent_only(self):
        posts = match_posts(parse_feed(RSS), "The Flight Deal", HOME, NOW, max_age_days=3)
        self.assertEqual([p["url"][-1] for p in posts], ["a", "c"])  # b arrives in Seattle, d is too old
        self.assertEqual(posts[0]["origins"], ["SEA"])
        self.assertEqual(posts[0]["price_text"], "$492")
        self.assertFalse(posts[0]["error_fare"])
        self.assertTrue(posts[1]["error_fare"])

    def test_atom_and_rupee_price(self):
        posts = match_posts(parse_feed(ATOM), "r/flightdeals", HOME, NOW, max_age_days=3)
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["origins"], ["DEL"])
        self.assertEqual(posts[0]["price_text"], "₹9,800")


class DigestTimingTests(unittest.TestCase):
    def test_first_run_sends(self):
        self.assertTrue(digest_due(NOW, (1, 13), None))

    def test_due_once_per_slot(self):
        # 15:00 now; the 13:00 slot passed. Sent at 13:20 -> not due; sent at 02:00 -> due.
        self.assertFalse(digest_due(NOW, (1, 13), "2026-10-14T13:20:00+00:00"))
        self.assertTrue(digest_due(NOW, (1, 13), "2026-10-14T02:00:00+00:00"))

    def test_slot_from_yesterday(self):
        early = datetime(2026, 10, 14, 0, 30, tzinfo=timezone.utc)  # before today's 01:00 slot
        self.assertFalse(digest_due(early, (1, 13), "2026-10-13T13:05:00+00:00"))
        self.assertTrue(digest_due(early, (1, 13), "2026-10-13T02:00:00+00:00"))


class SpecialOffersTests(unittest.TestCase):
    def test_keeps_roundtrips_only(self):
        payload = {"success": True, "data": [
            {"destination": "BKK", "price": 9000, "departure_at": "2026-12-01T01:00:00+05:30", "return_at": "2026-12-09T01:00:00+07:00"},
            {"destination": "DXB", "price": 4000, "departure_at": "2026-12-01T01:00:00+05:30"},  # one-way
        ]}
        with mock.patch.object(travelpayouts, "_get_json", return_value=payload):
            rows = travelpayouts.special_offers("DEL", "inr", "in", "token")
        self.assertEqual([r["destination"] for r in rows], ["BKK"])


if __name__ == "__main__":
    unittest.main()
