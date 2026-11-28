from dataclasses import replace
from datetime import date, time, timedelta
from unittest.mock import Mock

import pytest

from flight_search.airports import AirportInfo
from flight_search.cache import Cache
from flight_search.config import KARLSRUHE, SearchSettings
from flight_search.dates import DatePair
from flight_search.destinations import DestinationChoice
from flight_search.fli_api import RequestBudget
from flight_search.search import SearchRequest

TODAY = date(2026, 12, 1)
LISBON = AirportInfo(
    "LIS", "Lisbon Airport", "Lisbon", "PT", "large_airport", "EU", 38.77, -9.13
)


def weekend_query(*, max_requests: int = 20):
    from flight_search.weekend import WeekendQuery

    return WeekendQuery(
        start="2026-12-04",
        end="2026-12-13",
        depart_days=("fri",),
        return_days=("sun",),
        min_nights=2,
        max_nights=2,
        home=("FRA",),
        destination=DestinationChoice(codes=("LIS",)),
        center=KARLSRUHE,
        settings=SearchSettings(adults=2, currency="CHF"),
        max_requests=max_requests,
        max_candidates=3,
    )


def test_prepare_weekend_resolves_structured_search():
    from flight_search.weekend import prepare_weekend

    query = replace(
        weekend_query(),
        destination=DestinationChoice(codes=("LIS", "ZZZ")),
        depart_after="17:30",
        return_arrive_before="22:15",
        airline_codes=(" lh ", "u2", "LH"),
        allow_codeshare=True,
        batch_size=1,
    )
    airport_loader = Mock(return_value=(LISBON,))

    plan = prepare_weekend(query, today=TODAY, airport_loader=airport_loader)

    airport_loader.assert_called_once()
    assert isinstance(plan.request, SearchRequest)
    assert plan.request.home == ("FRA",)
    assert plan.request.destinations == (LISBON,)
    assert list(plan.warnings) == ["Unknown or unsupported destination code: ZZZ"]
    assert plan.request.pairs == (
        DatePair(date(2026, 12, 4), date(2026, 12, 6)),
        DatePair(date(2026, 12, 11), date(2026, 12, 13)),
    )
    assert plan.request.depart_window.after == time(17, 30)
    assert plan.request.return_window.arrive_before == time(22, 15)
    assert plan.request.settings == query.settings
    assert plan.request.airlines == frozenset({"LH", "U2"})
    assert plan.request.allow_codeshare is True
    assert plan.request.batch_size == 1
    assert plan.request.max_candidates == 3
    assert plan.estimated_requests == 10


def test_prepare_weekend_rejects_past_start_before_loading_airports():
    from flight_search.weekend import WeekendError, prepare_weekend

    airport_loader = Mock(side_effect=AssertionError("unexpected airport load"))

    with pytest.raises(WeekendError, match="in the past"):
        prepare_weekend(
            weekend_query(), today=date(2026, 12, 5), airport_loader=airport_loader
        )

    airport_loader.assert_not_called()


def test_weekend_resources_apply_the_preview_estimate_at_the_budget_boundary(tmp_path):
    from flight_search.weekend import WeekendBudgetError, prepare_weekend

    airport_loader = Mock(return_value=(LISBON,))
    at_limit = prepare_weekend(
        weekend_query(max_requests=10), today=TODAY, airport_loader=airport_loader
    )
    over_limit = prepare_weekend(
        weekend_query(max_requests=9), today=TODAY, airport_loader=airport_loader
    )

    assert at_limit.estimated_requests == over_limit.estimated_requests == 10
    cache_dir = tmp_path / "weekend"
    cache, budget = at_limit.create_resources(
        cache_dir=cache_dir, cache_ttl="30m", cache_enabled=False
    )

    assert isinstance(cache, Cache)
    assert cache.directory == cache_dir
    assert cache.ttl == timedelta(minutes=30)
    assert cache.enabled is False
    assert isinstance(budget, RequestBudget)
    assert budget.limit == at_limit.estimated_requests
    assert budget.used == 0

    with pytest.raises(WeekendBudgetError):
        over_limit.create_resources(
            cache_dir=cache_dir, cache_ttl="30m", cache_enabled=False
        )
