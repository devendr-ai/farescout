import sys
import types
import unittest
from unittest import mock

from farescout.detect import Deal
from farescout.verify import check_live


class FlightsNotFound(Exception):
    pass


class FakeQuery:
    def url(self):
        return "https://www.google.com/travel/flights/search?tfs=x"


def fake_fast_flights(result=None, raises=None):
    """A stand-in fast_flights module whose get_flights returns `result` or raises `raises`."""
    mod = types.ModuleType("fast_flights")
    mod.FlightsNotFound = FlightsNotFound
    mod.FlightQuery = lambda **kw: kw
    mod.Passengers = lambda **kw: kw
    mod.create_query = lambda **kw: FakeQuery()

    def get_flights(q):
        if raises:
            raise raises
        return result

    mod.get_flights = get_flights
    return mod


def deal(price=200.0):
    fare = {"departure_at": "2027-02-25T08:00:00-05:00", "return_at": "2027-03-11T10:00:00-08:00",
            "origin_airport": "EWR", "destination_airport": "LAX"}
    return Deal("NYC", "LAX", "2027-02", "usd", price, 400.0, "other_months", 0.5, False, fare)


def flights(*prices):
    return [types.SimpleNamespace(price=p) for p in prices]


class CheckLiveTests(unittest.TestCase):
    def run_check(self, mod, price=200.0):
        with mock.patch.dict(sys.modules, {"fast_flights": mod}), self.assertNoLogs("farescout.verify", "ERROR"):
            return check_live(deal(price), tolerance=0.15)

    def test_confirmed_within_tolerance(self):
        status, live, url = self.run_check(fake_fast_flights(flights(260, 225, 300)))
        self.assertEqual((status, live), ("confirmed", 225.0))
        self.assertTrue(url.startswith("https://www.google.com/travel/flights"))

    def test_higher_when_live_price_rose(self):
        status, live, _ = self.run_check(fake_fast_flights(flights(428, 429)), price=181)
        self.assertEqual((status, live), ("higher", 428.0))

    def test_not_found_is_an_error_not_sold_out(self):
        status, live, _ = self.run_check(fake_fast_flights(raises=FlightsNotFound("no flights")))
        self.assertEqual((status, live), ("error", None))

    def test_empty_results_is_an_error_not_sold_out(self):
        status, live, _ = self.run_check(fake_fast_flights(flights()))
        self.assertEqual((status, live), ("error", None))

    def test_network_failure_is_an_error(self):
        status, live, _ = self.run_check(fake_fast_flights(raises=ConnectionError("blocked")))
        self.assertEqual((status, live), ("error", None))


if __name__ == "__main__":
    unittest.main()
