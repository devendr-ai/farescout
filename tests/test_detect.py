import unittest
from datetime import date, timedelta

from farescout.config import DealRules
from farescout.detect import find_deals
from farescout.export import money
from farescout.store import Store

TODAY = date(2026, 10, 14)
RULES = DealRules(min_off=0.40, mistake_off=0.65, history_days=90, min_history_days=7, min_other_months=4)


def fare(price, dest="LIS"):
    return {"price": price, "destination": dest, "departure_at": "2027-01-12T09:00:00-05:00",
            "return_at": "2027-01-20T12:00:00+00:00", "airline": "TP", "transfers": 0}


class DetectTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.history = lambda o, d, m, c, since, before: self.store.history(o, d, m, c, since, before)

    def seed(self, price, days, month="2027-01", dest="LIS"):
        for i in range(1, days + 1):
            self.store.record(TODAY - timedelta(days=i), "NYC", dest, month, price, "usd")

    def test_history_baseline_flags_deal(self):
        self.seed(800, days=10)
        deals = find_deals({("NYC", "LIS", "2027-01"): fare(400)}, {"NYC": "usd"}, self.history, RULES, TODAY)
        self.assertEqual(len(deals), 1)
        d = deals[0]
        self.assertEqual(d.baseline_source, "history")
        self.assertEqual(d.baseline, 800)
        self.assertAlmostEqual(d.off, 0.5)
        self.assertFalse(d.mistake)

    def test_small_drop_is_not_a_deal(self):
        self.seed(800, days=10)
        deals = find_deals({("NYC", "LIS", "2027-01"): fare(600)}, {"NYC": "usd"}, self.history, RULES, TODAY)
        self.assertEqual(deals, [])

    def test_mistake_fare(self):
        self.seed(1000, days=10)
        deals = find_deals({("NYC", "LIS", "2027-01"): fare(250)}, {"NYC": "usd"}, self.history, RULES, TODAY)
        self.assertTrue(deals[0].mistake)

    def test_todays_price_is_not_its_own_baseline(self):
        self.seed(800, days=10)
        self.store.record(TODAY, "NYC", "LIS", "2027-01", 400, "usd")
        deals = find_deals({("NYC", "LIS", "2027-01"): fare(400)}, {"NYC": "usd"}, self.history, RULES, TODAY)
        self.assertEqual(deals[0].baseline, 800)

    def test_cold_start_uses_other_months(self):
        fares = {("NYC", "LIS", f"2027-0{m}"): fare(900) for m in range(2, 7)}
        fares[("NYC", "LIS", "2027-01")] = fare(450)
        deals = find_deals(fares, {"NYC": "usd"}, self.history, RULES, TODAY)
        self.assertEqual([d.month for d in deals], ["2027-01"])
        self.assertEqual(deals[0].baseline_source, "other_months")

    def test_no_baseline_no_deal(self):
        fares = {("NYC", "LIS", "2027-01"): fare(100), ("NYC", "LIS", "2027-02"): fare(900)}
        self.assertEqual(find_deals(fares, {"NYC": "usd"}, self.history, RULES, TODAY), [])

    def test_history_in_other_currency_ignored(self):
        for i in range(1, 11):
            self.store.record(TODAY - timedelta(days=i), "NYC", "LIS", "2027-01", 70000, "inr")
        deals = find_deals({("NYC", "LIS", "2027-01"): fare(400)}, {"NYC": "usd"}, self.history, RULES, TODAY)
        self.assertEqual(deals, [])


class StoreTests(unittest.TestCase):
    def test_record_keeps_daily_low(self):
        s = Store(":memory:")
        s.record(TODAY, "DEL", "BKK", "2026-12", 21000, "inr")
        s.record(TODAY, "DEL", "BKK", "2026-12", 18000, "inr")
        s.record(TODAY, "DEL", "BKK", "2026-12", 25000, "inr")
        self.assertEqual(s.history("DEL", "BKK", "2026-12", "inr", TODAY), [(TODAY.isoformat(), 18000.0)])

    def test_prune_drops_old_days_and_past_months(self):
        s = Store(":memory:")
        s.record(TODAY - timedelta(days=200), "DEL", "BKK", "2026-12", 1, "inr")
        s.record(TODAY, "DEL", "BKK", "2026-09", 1, "inr")
        s.record(TODAY, "DEL", "BKK", "2026-12", 1, "inr")
        s.prune(keep_days=97, today=TODAY)
        rows = s.db.execute("SELECT month, day FROM route_daily").fetchall()
        self.assertEqual(rows, [("2026-12", TODAY.isoformat())])


class MoneyTests(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(money(612.4, "usd"), "$612")
        self.assertEqual(money(1234567, "inr"), "₹12,34,567")
        self.assertEqual(money(950, "inr"), "₹950")
        self.assertEqual(money(23450, "inr"), "₹23,450")


if __name__ == "__main__":
    unittest.main()
