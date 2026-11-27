import json
from datetime import date, datetime, time, timedelta

from flight_search import fli_api
from flight_search.cache import Cache
from flight_search.combine import options_from_results
from flight_search.config import SearchSettings
from flight_search.discover import _batch_key, batch_codes, run_discovery
from flight_search.fli_api import RequestBudget, max_destinations
from flight_search.windows import DepartureWindow, ReturnWindow


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
        return_window=ReturnWindow(),
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
        return_window=ReturnWindow(),
        settings=SearchSettings(),
        cache=Cache(directory=tmp_path, ttl=timedelta(0)),
        budget=RequestBudget(10),
        batch_size=10,
        concurrency=1,
    )
    # 07:00 is outside the 18:00+ window even though Google's hour bound is
    # permissive, so nothing must be recorded.
    assert result.screens["BCN"].out == {}


def _two_flight_detail(calls):
    """Fake page: one 17:15 flight for 50 EUR and one 17:45 flight for 80 EUR."""

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
        base = datetime.combine(travel_date, datetime.min.time())
        early = base.replace(hour=17, minute=15)
        late = base.replace(hour=17, minute=45)
        if origins == ["FRA"]:
            return [
                FakeResult("FRA", "BCN", 50.0, early),
                FakeResult("FRA", "BCN", 80.0, late),
            ]
        return [
            FakeResult("BCN", "FRA", 50.0, early),
            FakeResult("BCN", "FRA", 80.0, late),
        ]

    return fake_detail


def _discover(cache, *, depart_window, return_window, depart=True):
    return run_discovery(
        destinations=("BCN",),
        home=("FRA",),
        depart_dates=[date(2026, 11, 13)] if depart else [],
        return_dates=[] if depart else [date(2026, 11, 15)],
        depart_window=depart_window,
        return_window=return_window,
        settings=SearchSettings(),
        cache=cache,
        budget=RequestBudget(10),
        batch_size=10,
        concurrency=1,
    )


def test_cached_discovery_honours_minute_window_outbound(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(fli_api, "detail_results", _two_flight_detail(calls))
    cache = Cache(directory=tmp_path, ttl=timedelta(hours=1))

    first = _discover(
        cache,
        depart_window=DepartureWindow(after=time(17, 0)),
        return_window=ReturnWindow(),
    )
    second = _discover(
        cache,
        depart_window=DepartureWindow(after=time(17, 30)),
        return_window=ReturnWindow(),
    )

    assert first.screens["BCN"].out == {"2026-11-13": 50.0}
    assert second.screens["BCN"].out == {"2026-11-13": 80.0}
    assert second.requests == 0
    assert len(calls) == 1


def test_cached_discovery_honours_minute_window_return(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(fli_api, "detail_results", _two_flight_detail(calls))
    cache = Cache(directory=tmp_path, ttl=timedelta(hours=1))

    first = _discover(
        cache,
        depart_window=DepartureWindow(),
        return_window=ReturnWindow(depart_after=time(17, 0)),
        depart=False,
    )
    second = _discover(
        cache,
        depart_window=DepartureWindow(),
        return_window=ReturnWindow(depart_after=time(17, 30)),
        depart=False,
    )

    assert first.screens["BCN"].ret == {"2026-11-15": 50.0}
    assert second.screens["BCN"].ret == {"2026-11-15": 80.0}
    assert second.requests == 0
    assert len(calls) == 1


def test_discovery_caches_unfiltered_flights_of_batch(monkeypatch, tmp_path):
    calls = []
    fake = _two_flight_detail(calls)
    monkeypatch.setattr(fli_api, "detail_results", fake)
    cache = Cache(directory=tmp_path, ttl=timedelta(hours=1))

    # 18:00+ admits neither flight, yet both belong in the cached payload.
    _discover(
        cache,
        depart_window=DepartureWindow(after=time(18, 0)),
        return_window=ReturnWindow(),
    )

    expected = [
        option.to_dict()
        for option in options_from_results(
            fake(["FRA"], ["BCN"], date(2026, 11, 13), None, SearchSettings())
        )
    ]
    payloads = [
        json.loads(path.read_text(encoding="utf-8"))["payload"]
        for path in tmp_path.glob("*.json")
    ]
    assert payloads == [expected]
    assert len(expected) == 2


def test_discovery_ignores_old_format_cache_entry(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(fli_api, "detail_results", _two_flight_detail(calls))
    cache = Cache(directory=tmp_path, ttl=timedelta(hours=1))
    window = DepartureWindow(after=time(17, 0))
    key = _batch_key(
        ("FRA",),
        ("BCN",),
        date(2026, 11, 13),
        "out",
        SearchSettings(),
        window.restrictions(),
    )
    cache.put(key, {"BCN": 999.0})

    result = _discover(cache, depart_window=window, return_window=ReturnWindow())

    assert result.failures == []
    assert result.requests == 1
    assert len(calls) == 1
    assert result.screens["BCN"].out == {"2026-11-13": 50.0}


def _seed_out_key_payload(cache, payload, window):
    key = _batch_key(
        ("FRA",),
        ("BCN",),
        date(2026, 11, 13),
        "out",
        SearchSettings(),
        window.restrictions(),
    )
    cache.put(key, payload)
    return key


def test_discovery_treats_undecodable_cached_list_as_miss(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(fli_api, "detail_results", _two_flight_detail(calls))
    cache = Cache(directory=tmp_path, ttl=timedelta(hours=1))
    window = DepartureWindow(after=time(17, 0))
    key = _seed_out_key_payload(cache, [{"price": 1}], window)

    result = _discover(cache, depart_window=window, return_window=ReturnWindow())

    assert result.failures == []
    assert result.requests == 1
    assert len(calls) == 1
    assert result.screens["BCN"].out == {"2026-11-13": 50.0}
    stored = cache.get(key)
    assert isinstance(stored, list)
    assert len(stored) == 2
    assert stored != [{"price": 1}]


def test_discovery_counts_old_format_entry_without_version_as_miss(
    monkeypatch, tmp_path
):
    calls = []
    monkeypatch.setattr(fli_api, "detail_results", _two_flight_detail(calls))
    cache = Cache(directory=tmp_path, ttl=timedelta(hours=1))
    window = DepartureWindow(after=time(17, 0))
    old_key = {
        "phase": "discover",
        "home": ["FRA"],
        "batch": ["BCN"],
        "date": "2026-11-13",
        "direction": "out",
        "restrictions": {"earliest_departure": 17},
        "settings": {
            "cabin": "ECONOMY",
            "max_stops": "ANY",
            "adults": 1,
            "currency": "EUR",
            "country": "DE",
            "language": "de-DE",
        },
    }
    cache.put(old_key, {"BCN": 999.0})
    cache.stats.hits = 0
    cache.stats.misses = 0

    result = _discover(cache, depart_window=window, return_window=ReturnWindow())

    assert result.failures == []
    assert cache.stats.hits == 0
    assert cache.stats.misses == 1
