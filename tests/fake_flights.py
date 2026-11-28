"""A deterministic, offline stand-in for ``fli_api.detail_results``.

The rows depend only on the origins, the destinations and the day (plus the
return day of a round-trip search), never on the time restrictions: like
Google's permissive whole-hour bound, the fake also returns rows that the
local window filter must drop. Every home -> foreign leg has a cheap 07:10
departure and a dearer 18:40 departure, so ``--depart-after 15`` (or 17) drops
the cheap one. Every foreign -> home leg has a 10:15 and a 20:05 departure.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

# Cheapest one-way base price per foreign airport; unknown codes cost 90.
BASE_PRICE = {
    "BCN": 58.0,
    "GRO": 55.0,
    "REU": 38.0,
    "LIS": 46.0,
    "FCO": 50.0,
    "CIA": 44.0,
    "PMI": 45.0,
    "AMS": 52.0,
}
HOME_OFFSET = {"FRA": 0.0, "STR": 6.0}
AIRLINES = (("LH", "Lufthansa"), ("FR", "Ryanair"), ("VY", "Vueling"))
MISSING = object()


class FakeAirport:
    def __init__(self, code: str) -> None:
        self.name = code
        self.value = code


class FakeAirline:
    def __init__(self, code: str, name: str) -> None:
        self.name = code
        self.value = name


class FakeLeg:
    def __init__(self, origin, destination, when, minutes, airline, number):
        self.airline = FakeAirline(*airline)
        self.flight_number = number
        self.departure_airport = FakeAirport(origin)
        self.arrival_airport = FakeAirport(destination)
        self.departure_datetime = when
        self.arrival_datetime = when + timedelta(minutes=minutes)
        self.duration = minutes
        self.aircraft = None


class SegmentLeg(FakeLeg):
    """A fli leg whose operator can be an airline, None or absent."""

    def __init__(self, origin, destination, when, airline, operating=MISSING):
        super().__init__(origin, destination, when, 120, airline, "100")
        if operating is not MISSING:
            self.operating_airline = (
                None if operating is None else FakeAirline(*operating)
            )


class SegmentResult:
    """A fli result whose self-transfer flag can be a bool, None or absent."""

    def __init__(self, legs, price=50.0, self_transfer=MISSING):
        self.legs = legs
        self.price = price
        self.currency = "EUR"
        self.duration = sum(leg.duration for leg in legs)
        self.stops = len(legs) - 1
        if self_transfer is not MISSING:
            self.self_transfer = self_transfer


class FakeResult:
    def __init__(self, origin, destination, price, when, slot):
        code_sum = sum(ord(ch) for ch in origin + destination)
        airline = AIRLINES[code_sum % len(AIRLINES)]
        minutes = 95 + code_sum % 60
        number = str(100 + code_sum % 800 + slot)
        self.legs = [FakeLeg(origin, destination, when, minutes, airline, number)]
        self.price = price
        self.currency = "EUR"
        self.duration = minutes
        self.stops = 0


def _at(day: date, hour: int, minute: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute)


def one_way_price(origin: str, destination: str, day: date) -> float:
    """The dearer of the two daily prices of a leg (the evening outbound)."""
    if origin in HOME_OFFSET:
        home, foreign = origin, destination
    else:
        home, foreign = destination, origin
    swing = (day.toordinal() + sum(ord(ch) for ch in foreign)) % 5 * 9.0
    return BASE_PRICE.get(foreign, 90.0) + HOME_OFFSET.get(home, 3.0) + swing


def _leg_rows(origin: str, destination: str, day: date) -> list[FakeResult]:
    price = one_way_price(origin, destination, day)
    if origin in HOME_OFFSET:
        # The cheap early outbound lies outside a "depart after 15/17" window.
        return [
            FakeResult(origin, destination, price - 12.0, _at(day, 7, 10), 0),
            FakeResult(origin, destination, price, _at(day, 18, 40), 1),
        ]
    return [
        FakeResult(origin, destination, price + 3.0, _at(day, 10, 15), 0),
        FakeResult(origin, destination, price - 2.0, _at(day, 20, 5), 1),
    ]


def fake_detail_results(
    origins,
    destinations,
    travel_date,
    restrictions,
    settings,
    *,
    return_date=None,
    top_n=1,
):
    """Drop-in replacement for ``fli_api.detail_results``."""
    if return_date is not None:
        rows = []
        for origin in origins:
            for destination in destinations:
                price = (
                    one_way_price(origin, destination, travel_date)
                    + one_way_price(destination, origin, return_date)
                    - 9.0
                )
                rows.append(
                    (
                        FakeResult(
                            origin, destination, price, _at(travel_date, 9, 0), 2
                        ),
                        FakeResult(
                            destination, origin, price, _at(return_date, 18, 0), 3
                        ),
                    )
                )
        return rows
    rows = []
    for origin in origins:
        for destination in destinations:
            rows.extend(_leg_rows(origin, destination, travel_date))
    return rows


FAILING_BATCH = frozenset({"LIS", "PMI"})
FAILING_DAY = date(2027, 3, 12)


def failing_batch_detail_results(
    origins,
    destinations,
    travel_date,
    restrictions,
    settings,
    *,
    return_date=None,
    top_n=1,
):
    """Like ``fake_detail_results``, but the outbound discovery batch of exactly
    LIS and PMI fails on 12 March 2027 (by codes and day, not by call order)."""
    if set(destinations) == FAILING_BATCH and travel_date == FAILING_DAY:
        raise RuntimeError("fake outage for this batch")
    return fake_detail_results(
        origins,
        destinations,
        travel_date,
        restrictions,
        settings,
        return_date=return_date,
        top_n=top_n,
    )


def empty_detail_results(*args, **kwargs):
    """Google answers every request without a single row."""
    return []
