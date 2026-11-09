from datetime import date, datetime, timedelta

from flight_search import fli_api, discover
from flight_search.cache import Cache
from flight_search.config import SearchSettings
from flight_search.discover import batch_codes, run_discovery
from flight_search.fli_api import max_destinations, RequestBudget
from flight_search.windows import DepartureWindow, ReturnArrivalWindow


class FakeAirport:
    def __init__(self, name):
        self.name = name
        self.value = name


class FakeAirline:
    name = "LH"
    value = "Lufthansa"


class FakeLeg:
    def __init__(self, origin, destination, when):
        self.airline = FakeAirline()
        self.flight_number = "100"
        self.departure_airport = FakeAirport(origin)
        self.arrival_airport = FakeAirport(destination)
        self.departure_datetime = when
        self.arrival_datetime = when + timedelta(hours=2)
        self.duration = 120
        self.aircraft = None


class FakeResult:
    def __init__(self, origin, destination, price, when):
        self.legs = [FakeLeg(origin, destination, when)]
        self.price = price
        self.currency = "EUR"
        self.duration = 120
        self.stops = 0


def test_batch_codes_respects_size():
    assert batch_codes(["A", "B", "C", "D", "E"], 2) == [
        ("A", "B"),
        ("C", "D"),
        ("E",),
    ]


def test_airport_limit_leaves_room_for_home_airports():
    assert max_destinations(4) == 10
    assert max_destinations(6) == 8
    assert max_destinations(20) == 1


def test_discovery_batches_and_records_prices(monkeypatch, tmp_path):
    calls = []

    def fake_detail(
        origins,
        destinations,
        travel_date,
        restrictions,
        settings,
        *,
        return_date=None,
        top_n=1,
    ):
        calls.append((tuple(origins), tuple(destinations), travel_date))
        when = datetime.combine(travel_date, datetime.min.time()).replace(hour=10)
        if origins == ["FRA"]:
            return [FakeResult("FRA", destinations[0], 50.0, when)]
        return [FakeResult(origins[0], "FRA", 60.0, when)]

    monkeypatch.setattr(fli_api, "detail_results", fake_detail)

    cache = Cache(directory=tmp_path, ttl=timedelta(0))
    result = run_discovery(
        destinations=("BCN", "MAD", "GRO"),
        home=("FRA",),
        depart_dates=[date(2026, 11, 13)],
        return_dates=[date(2026, 11, 15)],
        depart_window=DepartureWindow(),
        return_window=ReturnArrivalWindow(),
        settings=SearchSettings(),
        cache=cache,
        budget=RequestBudget(100),
        batch_size=2,
        concurrency=1,
    )

    # Two batches (BCN/MAD and GRO) in each direction.
    assert len(calls) == 4
    assert result.requests == 4
    assert result.failures == []
    # Destinations are sorted before batching: (BCN, GRO) and (MAD,).
    # The fake only ever prices the first code of a batch, mirroring the
    # partial coverage of a real page.
    assert result.screens["BCN"].out == {"2026-11-13": 50.0}
    assert result.screens["BCN"].ret == {"2026-11-15": 60.0}
    assert result.screens["MAD"].out == {"2026-11-13": 50.0}
    assert result.screens["GRO"].out == {}


def test_discovery_applies_exact_departure_window(monkeypatch, tmp_path):
    def fake_detail(
        origins,
        destinations,
        travel_date,
        restrictions,
        settings,
        *,
        return_date=None,
        top_n=1,
    ):
        when = datetime.combine(travel_date, datetime.min.time()).replace(hour=7)
        if origins == ["FRA"]:
            return [FakeResult("FRA", destinations[0], 50.0, when)]
        return []

    monkeypatch.setattr(fli_api, "detail_results", fake_detail)

    result = run_discovery(
        destinations=("BCN",),
        home=("FRA",),
        depart_dates=[date(2026, 11, 13)],
        return_dates=[],
        depart_window=DepartureWindow(after=datetime(2026, 1, 1, 18, 0).time()),
        return_window=ReturnArrivalWindow(),
        settings=SearchSettings(),
        cache=Cache(directory=tmp_path, ttl=timedelta(0)),
        budget=RequestBudget(10),
        batch_size=10,
        concurrency=1,
    )
    # 07:00 is outside the 18:00+ window even though Google's hour bound is
    # permissive, so nothing must be recorded.
    assert result.screens["BCN"].out == {}
