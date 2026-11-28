"""Browser tests of the local weekend search against simulated flights.

Run them with ``uv run --group e2e pytest -m e2e`` after a one-time
``uv run --group e2e playwright install --only-shell chromium``. The default
``uv run pytest`` deselects them, and without Playwright they are skipped.
"""

from __future__ import annotations

import sys
import time
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from threading import Thread

import pytest

pytest.importorskip("playwright")
sys.path.insert(0, str(Path(__file__).parents[1]))

from airport_factory import airport
from fake_flights import fake_detail_results
from werkzeug.serving import make_server

from flight_search import fli_api
from flight_search.config import KARLSRUHE, SearchSettings
from flight_search.destinations import DestinationChoice
from flight_search.web import create_app
from flight_search.weekend import WeekendQuery

AIRPORTS = (
    airport("BCN", "ES", "EU", municipality="Barcelona", lat=41.30, lon=2.08),
    airport("CIA", "IT", "EU", municipality="Rome", lat=41.80, lon=12.59),
    airport("FCO", "IT", "EU", municipality="Rome", lat=41.80, lon=12.25),
    airport("FRA", "DE", "EU", municipality="Frankfurt", lat=50.03, lon=8.56),
    airport("LIS", "PT", "EU", municipality="Lisbon", lat=38.77, lon=-9.13),
    airport("PMI", "ES", "EU", municipality="Palma", lat=39.55, lon=2.73),
)


def pytest_collection_modifyitems(items):
    for item in items:
        if Path(item.fspath).is_relative_to(Path(__file__).parent):
            item.add_marker(pytest.mark.e2e)


def _defaults(**changes) -> WeekendQuery:
    start = date.today() + timedelta(days=14)
    start += timedelta(days=(4 - start.weekday()) % 7)
    query = WeekendQuery(
        start=start.isoformat(),
        end=(start + timedelta(days=16)).isoformat(),
        depart_days=("fri",),
        return_days=("sun",),
        min_nights=2,
        max_nights=2,
        home=("FRA",),
        destination=DestinationChoice(region="europe"),
        center=KARLSRUHE,
        settings=SearchSettings(currency="EUR"),
        max_requests=200,
    )
    return replace(query, **changes)


@pytest.fixture
def delays() -> dict[str, list[float]]:
    """Seconds the next one-way fetches to an airport sleep, by airport code.

    A test fills it after the first search, e.g. ``delays["LIS"] = [3.0]`` slows
    the next confirming fetch to Lisbon; each fetch takes the first entry.
    """
    return {}


@pytest.fixture
def app_url(monkeypatch, request, delays):
    """A local server whose searches run the real core against fake flights.

    Parametrise it indirectly with a dict to change WeekendQuery defaults, e.g.
    ``@pytest.mark.parametrize("app_url", [{"per_city": 1}], indirect=True)``.
    """

    def slow_detail_results(origins, destinations, *args, **kwargs):
        if kwargs.get("return_date") is None:
            for code in destinations:
                if delays.get(code):
                    time.sleep(delays[code].pop(0))
        return fake_detail_results(origins, destinations, *args, **kwargs)

    monkeypatch.setattr(fli_api, "detail_results", slow_detail_results)
    app = create_app(
        _defaults(**getattr(request, "param", {})),
        configured_regions={},
        airport_loader=lambda *, include_small: AIRPORTS,
        cache_enabled=False,
    )
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    thread.join()
