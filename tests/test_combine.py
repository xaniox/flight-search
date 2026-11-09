from datetime import date, datetime

from flight_search.combine import (
    FlightOption,
    LegInfo,
    combine_itineraries,
    filter_departures,
    filter_return_legs,
    options_from_results,
    reduce_best,
)
from flight_search.windows import DepartureWindow, ReturnWindow


def make_option(
    origin: str,
    destination: str,
    depart: str,
    arrive: str,
    price: float,
    *,
    stops: int = 0,
    duration: int = 120,
    airline: str = "LH",
    number: str = "123",
) -> FlightOption:
    leg = LegInfo(
        airline=airline,
        airline_name="Lufthansa",
        flight_number=number,
        origin=origin,
        destination=destination,
        departure=depart,
        arrival=arrive,
        duration=duration,
    )
    return FlightOption(
        price=price,
        currency="EUR",
        departure=depart,
        arrival=arrive,
        stops=stops,
        duration=duration,
        legs=(leg,),
    )


def test_reduce_best_keeps_cheapest_per_airport_pair():
    options = [
        make_option("SXB", "BCN", "2026-11-13T16:00:00", "2026-11-13T17:50:00", 100),
        make_option("SXB", "BCN", "2026-11-13T08:00:00", "2026-11-13T09:50:00", 80),
        make_option("FRA", "BCN", "2026-11-13T11:00:00", "2026-11-13T13:00:00", 90),
    ]
    best = reduce_best(options)
    assert set(best) == {("SXB", "BCN"), ("FRA", "BCN")}
    assert best[("SXB", "BCN")].price == 80


def test_combine_labels_open_jaw_and_sorts_by_total():
    outbound = [
        make_option("FRA", "BCN", "2026-11-13T10:00:00", "2026-11-13T12:00:00", 90),
        make_option("SXB", "BCN", "2026-11-13T16:00:00", "2026-11-13T17:50:00", 100),
        make_option("SXB", "GRO", "2026-11-13T14:45:00", "2026-11-13T16:35:00", 60),
    ]
    inbound = [
        make_option("BCN", "STR", "2026-11-15T18:00:00", "2026-11-15T20:00:00", 50),
        make_option("GRO", "FKB", "2026-11-15T18:20:00", "2026-11-15T20:10:00", 40),
        make_option("BCN", "SXB", "2026-11-15T19:00:00", "2026-11-15T21:00:00", 70),
    ]
    itineraries = combine_itineraries(
        city_key="metro:barcelona",
        city="Barcelona",
        country="ES",
        city_codes=("BCN", "GRO"),
        depart_date=date(2026, 11, 13),
        return_date=date(2026, 11, 15),
        outbound_options=outbound,
        return_options=inbound,
    )
    assert itineraries[0].total == 100  # SXB->GRO 60 + GRO->FKB 40
    assert itineraries[0].open_jaw_label == "home"  # SXB out, FKB back, GRO both ways
    assert itineraries[0].nights == 2

    labels = {it.open_jaw_label for it in itineraries}
    assert "home" in labels  # SXB out, FKB back
    assert "dest" in labels  # BCN in, GRO out
    assert "both" in labels  # SXB/BCN out, GRO/FKB back
    assert "" in labels  # same airports both ways
    assert all(a.total <= b.total for a, b in zip(itineraries, itineraries[1:]))


def test_options_from_results_skips_unpriced_and_tuple_rows():
    class FakeAirport:
        def __init__(self, name, value=None):
            self.name = name
            self.value = value or name

    class FakeAirline:
        name = "_XQ"
        value = "SunExpress"

    class FakeLeg:
        airline = FakeAirline()
        flight_number = "7152"
        departure_airport = FakeAirport("SXB")
        arrival_airport = FakeAirport("BCN")
        departure_datetime = datetime(2026, 11, 13, 14, 45)
        arrival_datetime = datetime(2026, 11, 13, 16, 35)
        duration = 110
        aircraft = "B737"

    class FakeResult:
        legs = [FakeLeg()]
        price = 88.0
        currency = "EUR"
        duration = 110
        stops = 0

    class Unpriced(FakeResult):
        price = None

    options = options_from_results([FakeResult(), Unpriced(), (FakeResult(), FakeResult())])
    assert len(options) == 1
    assert options[0].origin == "SXB"
    assert options[0].destination == "BCN"
    assert options[0].legs[0].airline == "XQ"  # underscore stripped
    assert options[0].currency == "EUR"


def test_exact_window_filters():
    options = [
        make_option("SXB", "BCN", "2026-11-13T17:10:00", "2026-11-13T19:00:00", 80),
        make_option("SXB", "BCN", "2026-11-13T18:30:00", "2026-11-13T20:20:00", 90),
    ]
    depart_window = DepartureWindow(after=datetime(2026, 1, 1, 18, 0).time())
    assert [o.price for o in filter_departures(options, depart_window)] == [90]

    returns = [
        make_option("BCN", "SXB", "2026-11-15T19:00:00", "2026-11-15T21:00:00", 50),
        make_option("BCN", "SXB", "2026-11-15T22:00:00", "2026-11-16T00:30:00", 40),
    ]
    window = ReturnWindow(arrive_before=datetime(2026, 1, 1, 22, 0).time())
    assert [o.price for o in filter_return_legs(returns, window, date(2026, 11, 15))] == [50]

    late_window = ReturnWindow(depart_after=datetime(2026, 1, 1, 20, 0).time())
    assert [
        o.price for o in filter_return_legs(returns, late_window, date(2026, 11, 15))
    ] == [40]


def test_option_roundtrip_serialisation():
    option = make_option("SXB", "BCN", "2026-11-13T14:45:00", "2026-11-13T16:35:00", 88.0)
    restored = FlightOption.from_dict(option.to_dict())
    assert restored == option
