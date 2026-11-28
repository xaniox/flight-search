"""PR 3 C4: equally priced itineraries are ordered by their stops, none is dropped."""

from datetime import date

from flight_search.airports import CityGroup
from flight_search.candidates import Candidate
from flight_search.combine import FlightOption, LegInfo, combine_itineraries
from flight_search.dates import DatePair
from flight_search.detail import rank_itineraries
from flight_search.windows import DepartureWindow, ReturnWindow


def make_option(
    origin: str,
    destination: str,
    day: str,
    price: float,
    *,
    stops: int = 0,
    number: str = "100",
) -> FlightOption:
    depart = f"{day}T08:00:00"
    arrive = f"{day}T10:00:00"
    leg = LegInfo(
        airline="LH",
        airline_name="Lufthansa",
        flight_number=number,
        origin=origin,
        destination=destination,
        departure=depart,
        arrival=arrive,
        duration=120,
    )
    return FlightOption(
        price=price,
        currency="EUR",
        departure=depart,
        arrival=arrive,
        stops=stops,
        duration=120,
        legs=(leg,),
    )


def combine(outbound: list[FlightOption], inbound: list[FlightOption]):
    return combine_itineraries(
        city_key="BCN",
        city="Barcelona",
        country="ES",
        city_codes=("BCN",),
        depart_date=date(2026, 11, 13),
        return_date=date(2026, 11, 15),
        outbound_options=outbound,
        return_options=inbound,
    )


def city(key: str) -> CityGroup:
    return CityGroup(key=key, display=key, country="XX", airports=())


def candidate(key: str, depart: date, ret: date) -> Candidate:
    return Candidate(
        city=city(key),
        pair=DatePair(depart, ret),
        out_price=0,
        ret_price=0,
        estimate=0,
    )


EARLY = DatePair(date(2026, 11, 6), date(2026, 11, 8))
LATE = DatePair(date(2026, 11, 13), date(2026, 11, 15))


def rank(*specs: tuple[str, DatePair, float, int]):
    """One candidate per (city key, dates, price per direction, stops per direction)."""
    candidates = []
    options = {}
    for key, pair, price, stops in specs:
        candidates.append(candidate(key, pair.depart, pair.ret))
        options[(key, pair.depart, "out")] = [
            make_option(
                "SXB", key, pair.depart.isoformat(), price, stops=stops, number=key
            )
        ]
        options[(key, pair.ret, "ret")] = [
            make_option(
                key, "SXB", pair.ret.isoformat(), price, stops=stops, number=key
            )
        ]
    return rank_itineraries(
        candidates,
        options,
        depart_window=DepartureWindow(),
        return_window=ReturnWindow(),
    )


def test_combine_equal_total_puts_fewer_stops_first():
    result = combine(
        [
            make_option("SXB", "BCN", "2026-11-13", 100, stops=1, number="1"),
            make_option("FRA", "BCN", "2026-11-13", 100, stops=0, number="2"),
        ],
        [make_option("BCN", "SXB", "2026-11-15", 100, number="3")],
    )

    assert [item.out.stops for item in result] == [0, 1]


def test_combine_equal_total_counts_stops_of_both_directions():
    result = combine(
        [make_option("SXB", "BCN", "2026-11-13", 100, number="1")],
        [
            make_option("BCN", "SXB", "2026-11-15", 100, stops=2, number="2"),
            make_option("BCN", "FRA", "2026-11-15", 100, stops=0, number="3"),
        ],
    )

    assert [item.ret.stops for item in result] == [0, 2]


def test_combine_cheaper_total_comes_first_despite_more_stops_guard():
    result = combine(
        [
            make_option("SXB", "BCN", "2026-11-13", 120, stops=0, number="1"),
            make_option("FRA", "BCN", "2026-11-13", 80, stops=2, number="2"),
        ],
        [make_option("BCN", "SXB", "2026-11-15", 100, number="3")],
    )

    assert [item.total for item in result] == [180, 220]
    assert [item.out.stops for item in result] == [2, 0]


def test_combine_keeps_the_itinerary_with_more_stops_guard():
    result = combine(
        [
            make_option("SXB", "BCN", "2026-11-13", 100, stops=1, number="1"),
            make_option("FRA", "BCN", "2026-11-13", 100, stops=0, number="2"),
        ],
        [make_option("BCN", "SXB", "2026-11-15", 100, number="3")],
    )

    assert len(result) == 2


def test_rank_equal_total_puts_fewer_stops_first_despite_later_dates():
    result = rank(("AAA", EARLY, 100, 1), ("BBB", LATE, 100, 0))

    assert [item.city_key for item in result] == ["BBB", "AAA"]


def test_rank_equal_total_and_stops_fall_back_to_dates_guard():
    result = rank(("BBB", LATE, 100, 1), ("AAA", EARLY, 100, 1))

    assert [item.city_key for item in result] == ["AAA", "BBB"]


def test_rank_cheaper_total_comes_first_despite_more_stops_guard():
    result = rank(("AAA", EARLY, 120, 0), ("BBB", LATE, 80, 2))

    assert [item.city_key for item in result] == ["BBB", "AAA"]


def test_rank_keeps_the_equally_priced_itinerary_with_more_stops_guard():
    result = rank(("AAA", EARLY, 100, 1), ("BBB", LATE, 100, 0))

    assert {item.city_key for item in result} == {"AAA", "BBB"}
