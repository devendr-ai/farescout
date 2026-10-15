import os
import unittest
from datetime import date
from unittest import mock

from farescout import __main__ as cli
from farescout import serpapi
from farescout.config import Config, Origin, SerpApiRules, VerifyRules
from farescout.detect import Deal
from farescout.store import Store

TODAY = date(2026, 10, 15)


def deal(dest="LIS", price=250.0, mistake=True):
    fare = {"departure_at": "2027-02-11T08:00:00-08:00", "return_at": "2027-02-21T10:00:00+00:00",
            "origin_airport": "SEA", "destination_airport": dest}
    off = 0.7 if mistake else 0.5
    return Deal("SEA", dest, "2027-02", "usd", price, 900.0, "history", off, mistake, fare)


RESPONSE = {
    "search_metadata": {"google_flights_url": "https://www.google.com/travel/flights?tfs=abc"},
    "best_flights": [{"price": 262}, {"price": 310}],
    "other_flights": [{"price": 255}],
    "price_insights": {"lowest_price": 255, "price_level": "low", "typical_price_range": [780, 1100]},
}


class CheckTests(unittest.TestCase):
    def test_confirmed_with_google_typical_range(self):
        with mock.patch.object(serpapi, "_get", return_value=RESPONSE) as get:
            r = serpapi.check(deal(), "key", tolerance=0.15)
        params = get.call_args.args[1]
        self.assertEqual((params["departure_id"], params["arrival_id"]), ("SEA", "LIS"))
        self.assertEqual((params["outbound_date"], params["return_date"], params["type"]), ("2027-02-11", "2027-02-21", 1))
        self.assertEqual(params["stops"], 0)
        self.assertEqual(r["status"], "confirmed")
        self.assertEqual(r["live_price"], 255.0)
        self.assertEqual((r["typical_low"], r["typical_high"], r["price_level"]), (780.0, 1100.0, "low"))
        self.assertEqual(r["url"], "https://www.google.com/travel/flights?tfs=abc")

    def test_higher(self):
        with mock.patch.object(serpapi, "_get", return_value={**RESPONSE, "best_flights": [{"price": 640}], "other_flights": []}):
            self.assertEqual(serpapi.check(deal(), "key", 0.15)["status"], "higher")

    def test_error_response_is_not_sold_out(self):
        with mock.patch.object(serpapi, "_get", return_value={"error": "Google Flights hasn't returned any results."}):
            r = serpapi.check(deal(), "key", 0.15)
        self.assertEqual((r["status"], r["live_price"]), ("error", None))


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.addCleanup(self.store.db.close)
        self.cfg = Config(
            origins=[Origin("SEA", "usd", ("us",))],
            verify=VerifyRules(max_per_run=12, delay_seconds=0),
            serpapi=SerpApiRules(monthly_budget=240, daily_budget=8, max_per_run=3),
        )

    def run_verify(self, deals, serp_result=None, left=200):
        serp_result = serp_result or {"status": "confirmed", "live_price": 255.0, "url": "u", "price_level": "low",
                                      "typical_low": 780.0, "typical_high": 1100.0}
        with mock.patch.dict(os.environ, {"SERPAPI_API_KEY": "key"}), \
                mock.patch.object(serpapi, "searches_left", return_value=left), \
                mock.patch.object(serpapi, "check", return_value=serp_result) as serp, \
                mock.patch.object(cli, "check_live", return_value=("confirmed", 400.0, "g")) as ff:
            out = cli.verify_deals(self.cfg, self.store, deals, False, TODAY)
        return out, serp, ff

    def test_only_mistake_fares_use_serpapi(self):
        (v, checks, serp_checks), serp, ff = self.run_verify([deal("LIS"), deal("NRT", mistake=False)])
        self.assertEqual((serp_checks, checks), (1, 1))
        self.assertEqual(serp.call_args.args[0].destination, "LIS")
        self.assertEqual(ff.call_args.args[0].destination, "NRT")

    def test_per_run_and_daily_budget(self):
        mistakes = [deal(d) for d in ("LIS", "NRT", "ICN", "BKK", "SIN")]
        (_, checks, serp_checks), _, _ = self.run_verify(mistakes)
        self.assertEqual((serp_checks, checks), (3, 2))  # 3 per run; the rest go to fast-flights
        self.assertEqual(self.store.count_usage("serpapi", TODAY.isoformat()), 3)
        for _ in range(5):
            self.store.add_usage("serpapi", [TODAY.isoformat()])
        (_, _, serp_checks), serp, _ = self.run_verify([deal("MEX")])
        self.assertEqual(serp_checks, 0)  # daily budget of 8 used up
        serp.assert_not_called()

    def test_account_with_no_searches_left(self):
        (_, checks, serp_checks), serp, _ = self.run_verify([deal()], left=0)
        self.assertEqual((serp_checks, checks), (0, 1))
        serp.assert_not_called()

    def test_serpapi_error_falls_back_to_fast_flights(self):
        err = {"status": "error", "live_price": None, "url": None, "price_level": None, "typical_low": None, "typical_high": None}
        (v, checks, serp_checks), _, ff = self.run_verify([deal()], serp_result=err)
        self.assertEqual((serp_checks, checks), (1, 1))
        ff.assert_called_once()

    def test_confirmed_mistake_is_cached_for_a_day(self):
        self.run_verify([deal()])
        (v, checks, serp_checks), serp, _ = self.run_verify([deal()])
        self.assertEqual((serp_checks, checks), (0, 0))
        only = next(iter(v.values()))
        self.assertEqual((only["source"], only["typical_low"]), ("serpapi", 780.0))


if __name__ == "__main__":
    unittest.main()
