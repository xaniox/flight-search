from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

from airport_factory import airport
from test_web import start_search, wait_for_final_state

from flight_search.config import KARLSRUHE, SearchSettings
from flight_search.destinations import DestinationChoice
from flight_search.web import create_app
from flight_search.weekend import WeekendQuery

AIRPORTS = (
    airport("FRA", lat=50.03, lon=8.57),
    airport("STR", lat=48.69, lon=9.22),
    airport("BER", lat=52.36, lon=13.50),
    airport("SXB", "FR", lat=48.54, lon=7.63),
    airport("LIS", "PT", lat=38.77, lon=-9.13),
)


def browser_with_target(choice, runner):
    start = date.today() + timedelta(days=7)
    start += timedelta(days=(4 - start.weekday()) % 7)
    return create_app(
        WeekendQuery(
            start=start.isoformat(),
            end=(start + timedelta(days=2)).isoformat(),
            depart_days=("fri",),
            return_days=("sun",),
            min_nights=2,
            max_nights=2,
            home=("FRA",),
            destination=choice,
            center=KARLSRUHE,
            settings=SearchSettings(),
            max_requests=10,
            max_candidates=4,
        ),
        configured_regions={},
        search_runner=runner,
        airport_loader=lambda *, include_small: AIRPORTS,
    ).test_client()


def test_adding_country_keeps_configured_country_and_radius_together():
    runner = Mock(return_value=SimpleNamespace(itineraries=list))
    client = browser_with_target(
        DestinationChoice(
            region="weekend", countries=frozenset({"DE"}), max_distance_km=150
        ),
        runner,
    )
    catalog = client.get("/api/catalogs").get_json()
    defaults = catalog["defaults"]
    assert defaults["countries"] == []
    [preset] = defaults["regions"]
    assert preset in catalog["regions"]

    path = start_search(client, regions=[preset], countries=["PT"])
    state = wait_for_final_state(client, path)
    assert state["status"] == "done", state
    runner.assert_called_once()
    [request] = runner.call_args.args
    assert sorted(item.iata for item in request.destinations) == ["LIS", "STR"]


def test_simple_weekend_default_preserves_its_existing_region_id():
    client = browser_with_target(DestinationChoice(region="weekend"), Mock())
    defaults = client.get("/api/catalogs").get_json()["defaults"]
    assert defaults["regions"] == ["weekend"]
    assert defaults["countries"] == []
