from datetime import date, timedelta

from flight_search import fli_api
from flight_search.cache import Cache
from flight_search.config import SearchSettings
from flight_search.detail import fetch_options
from flight_search.fli_api import RequestBudget

DAY = date(2026, 11, 13)


def _record_detail_results(monkeypatch, results=None):
    calls = []

    def fake(*args, **kwargs):
        calls.append((args, kwargs))
        return results if results is not None else []

    monkeypatch.setattr(fli_api, "detail_results", fake)
    return calls


def test_fetch_leg_out_searches_home_to_codes(monkeypatch):
    calls = _record_detail_results(monkeypatch, results=["sentinel"])
    settings = SearchSettings()
    restrictions = object()

    result = fli_api.fetch_leg(
        ("FRA", "STR"), ("BCN", "PMI"), DAY, "out", restrictions, settings
    )

    assert result == ["sentinel"]
    ((args, _),) = calls
    assert args == (["FRA", "STR"], ["BCN", "PMI"], DAY, restrictions, settings)


def test_fetch_leg_ret_searches_codes_to_home(monkeypatch):
    calls = _record_detail_results(monkeypatch, results=["sentinel"])
    settings = SearchSettings()
    restrictions = object()

    result = fli_api.fetch_leg(
        ("FRA", "STR"), ("BCN", "PMI"), DAY, "ret", restrictions, settings
    )

    assert result == ["sentinel"]
    ((args, _),) = calls
    assert args == (["BCN", "PMI"], ["FRA", "STR"], DAY, restrictions, settings)


def test_fetch_leg_passes_none_restrictions_through(monkeypatch):
    calls = _record_detail_results(monkeypatch)

    fli_api.fetch_leg(("FRA",), ("BCN",), DAY, "out", None, SearchSettings())

    ((args, _),) = calls
    assert args[3] is None


def test_detail_fetch_options_routes_through_fetch_leg(monkeypatch, tmp_path):
    seen = []

    def fake_fetch_leg(home, codes, day, direction, restrictions, settings):
        seen.append((home, codes, day, direction, restrictions, settings))
        return []

    monkeypatch.setattr(fli_api, "fetch_leg", fake_fetch_leg, raising=False)
    monkeypatch.setattr(fli_api, "detail_results", lambda *a, **k: [])
    settings = SearchSettings()

    fetch_options(
        home=("FRA",),
        city_codes=("BCN",),
        day=DAY,
        direction="ret",
        restrictions=None,
        settings=settings,
        cache=Cache(directory=tmp_path, ttl=timedelta(0)),
        budget=RequestBudget(),
    )

    assert seen == [(("FRA",), ("BCN",), DAY, "ret", None, settings)]


def test_discovery_worker_routes_through_fetch_leg(monkeypatch, tmp_path):
    from flight_search.discover import run_discovery
    from flight_search.windows import DepartureWindow, ReturnWindow

    seen = []

    def fake_fetch_leg(home, codes, day, direction, restrictions, settings):
        seen.append((tuple(home), tuple(codes), day, direction))
        return []

    monkeypatch.setattr(fli_api, "fetch_leg", fake_fetch_leg, raising=False)
    monkeypatch.setattr(fli_api, "detail_results", lambda *a, **k: [])

    run_discovery(
        destinations=("BCN",),
        home=("FRA",),
        depart_dates=[DAY],
        return_dates=[DAY + timedelta(days=2)],
        depart_window=DepartureWindow(),
        return_window=ReturnWindow(),
        settings=SearchSettings(),
        cache=Cache(directory=tmp_path, ttl=timedelta(0)),
        budget=RequestBudget(100),
        batch_size=2,
        concurrency=1,
    )

    assert sorted(seen) == [
        (("FRA",), ("BCN",), DAY, "out"),
        (("FRA",), ("BCN",), DAY + timedelta(days=2), "ret"),
    ]
