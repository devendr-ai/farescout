"""Confirm cached deals against live Google Flights prices via the fast-flights library.

Keep request volume low (a few dozen checks a day). This makes no attempt to get
around blocks: if Google refuses a request, the deal is shown as not checked.
"""

from __future__ import annotations

import logging

from .detect import Deal

log = logging.getLogger(__name__)


def trip_key(deal: Deal) -> str:
    f = deal.fare
    return "|".join(
        [
            deal.origin,
            deal.destination,
            (f.get("departure_at") or "")[:10],
            (f.get("return_at") or "")[:10],
            deal.currency,
        ]
    )


def google_flights_query_url(deal: Deal) -> str | None:
    """Exact-itinerary Google Flights link. Needs fast-flights installed."""
    q = _build_query(deal)
    return q.url() if q is not None else None


def _build_query(deal: Deal):
    try:
        from fast_flights import FlightQuery, Passengers, create_query
    except ImportError:
        return None
    f = deal.fare
    depart = (f.get("departure_at") or "")[:10]
    ret = (f.get("return_at") or "")[:10]
    if not depart or not ret:
        return None
    frm = f.get("origin_airport") or deal.origin
    to = f.get("destination_airport") or deal.destination
    return create_query(
        flights=[
            FlightQuery(date=depart, from_airport=frm, to_airport=to),
            FlightQuery(date=ret, from_airport=to, to_airport=frm),
        ],
        seat="economy",
        trip="round-trip",
        passengers=Passengers(adults=1),
        language="en-US",
        currency=deal.currency.upper(),
    )


def check_live(deal: Deal, tolerance: float) -> tuple[str, float | None, str | None]:
    """Return (status, live_price, url). Status: confirmed | higher | error | unchecked.

    An empty answer is reported as "error", not as sold out: Google returns empty or
    error pages to rate-limited and cloud IPs for routes that do have flights, so an
    empty result can't be told apart from a real "no flights on these dates".
    """
    q = _build_query(deal)
    if q is None:
        return "unchecked", None, None
    url = q.url()
    try:
        from fast_flights import FlightsNotFound, get_flights
    except ImportError:
        return "unchecked", None, url
    try:
        results = get_flights(q)
    except FlightsNotFound:
        log.warning("live check for %s-%s got no results from Google", deal.origin, deal.destination)
        return "error", None, url
    except Exception as e:  # network errors, blocks, parser changes
        log.warning("live check failed for %s-%s: %s", deal.origin, deal.destination, e)
        return "error", None, url
    prices = [r.price for r in results if getattr(r, "price", None)]
    if not prices:
        log.warning("live check for %s-%s got no prices from Google", deal.origin, deal.destination)
        return "error", None, url
    live = float(min(prices))
    status = "confirmed" if live <= deal.price * (1 + tolerance) else "higher"
    return status, live, url
