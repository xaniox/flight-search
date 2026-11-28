from datetime import date, timedelta
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace
from unittest.mock import Mock

from airport_factory import airport

from flight_search.combine import FlightOption, Itinerary, LegInfo
from flight_search.config import KARLSRUHE, SearchSettings
from flight_search.destinations import DestinationChoice
from flight_search.weekend import WeekendQuery

AIRPORTS = (
    airport("FRA", municipality="Frankfurt"),
    airport("LIS", "PT", municipality="Lisbon"),
    airport("JFK", "US", "NA", municipality="New York"),
)


def app_for(runner, *, per_city=None, **options):
    from flight_search.web import create_app

    start = date.today() + timedelta(days=7)
    start += timedelta(days=(4 - start.weekday()) % 7)
    end = start + timedelta(days=2)
    return create_app(
        WeekendQuery(
            start=start.isoformat(),
            end=end.isoformat(),
            depart_days=("fri",),
            return_days=("sun",),
            min_nights=2,
            max_nights=2,
            home=("FRA",),
            destination=DestinationChoice(region="europe"),
            center=KARLSRUHE,
            settings=SearchSettings(currency="CHF"),
            max_requests=10,
            max_candidates=4,
            airline_codes=("LH",),
            **({} if per_city is None else {"per_city": per_city}),
        ),
        configured_regions={"transatlantic": frozenset({"US"})},
        search_runner=runner,
        airport_loader=lambda *, include_small: AIRPORTS,
        **options,
    )


def confirmed_pair(request):
    pair = request.pairs[0]
    outbound = LegInfo(
        "LH",
        "Lufthansa",
        "123",
        "FRA",
        "LIS",
        f"{pair.depart}T18:00",
        f"{pair.depart}T20:00",
        180,
    )
    inbound = LegInfo(
        "LH",
        "Lufthansa",
        "124",
        "LIS",
        "FRA",
        f"{pair.ret}T16:00",
        f"{pair.ret}T20:00",
        180,
    )
    return Itinerary(
        city_key="LIS",
        city="Lisbon",
        country="PT",
        city_codes=("LIS",),
        depart_date=pair.depart,
        return_date=pair.ret,
        out=FlightOption(
            100, "CHF", outbound.departure, outbound.arrival, 0, 180, (outbound,)
        ),
        ret=FlightOption(
            90, "CHF", inbound.departure, inbound.arrival, 0, 180, (inbound,)
        ),
    )


def start_search(client, **fields):
    response = client.post("/api/searches", json=fields)
    assert response.status_code == 202, response.get_json()
    search_id = response.get_json()["id"]
    assert isinstance(search_id, str) and search_id
    return f"/api/searches/{search_id}"


def wait_for_final_state(client, path):
    deadline = monotonic() + 5
    while monotonic() < deadline:
        response = client.get(path)
        assert response.status_code == 200
        state = response.get_json()
        if state["status"] != "running":
            return state
        sleep(0.01)
    raise AssertionError(f"search did not finish: {path}")


def test_web_serves_form_and_local_catalogs():
    client = app_for(Mock()).test_client()

    page = client.get("/")
    assert page.status_code == 200
    assert b"<form" in page.data.lower()
    response = client.get("/api/catalogs")
    assert response.status_code == 200
    catalogs = response.get_json()

    assert {item["code"] for item in catalogs["airports"]} == {"FRA", "LIS", "JFK"}
    frankfurt = next(item for item in catalogs["airports"] if item["code"] == "FRA")
    assert {key: frankfurt[key] for key in ("name", "city", "country")} == {
        "name": "FRA Airport",
        "city": "Frankfurt",
        "country": "DE",
    }
    assert set(catalogs["regions"]) == {"europe", "weekend", "transatlantic"}
    assert set(catalogs["countries"]) == {"DE", "PT", "US"}
    airlines = {item["code"]: item["name"] for item in catalogs["airlines"]}
    assert airlines["LH"]
    assert len(airlines) > 1
    assert catalogs["defaults"]["home"] == ["FRA"]
    assert catalogs["defaults"]["airline_codes"] == ["LH"]


def test_web_command_uses_waitress_on_loopback(monkeypatch):
    import waitress

    from flight_search.cli import main

    serve = Mock()
    monkeypatch.setattr(waitress, "serve", serve)

    assert main(["web"]) == 0
    serve.assert_called_once()
    assert serve.call_args.kwargs["host"] == "127.0.0.1"


def test_search_reports_both_phases_then_returns_confirmed_pairs(tmp_path):
    discovery_ready, continue_discovery = Event(), Event()
    confirmation_ready, continue_confirmation = Event(), Event()
    cache_dir = tmp_path / "cache"

    def runner(request, *, cache, budget, progress):
        assert request.home == ("FRA",)
        assert [item.iata for item in request.destinations] == ["LIS"]
        assert request.airlines == frozenset({"TP"})
        assert request.settings.currency == "CHF"
        assert budget.limit == 10
        assert cache.directory == cache_dir
        assert cache.ttl == timedelta(minutes=30)
        assert cache.enabled is False
        update = progress.start("Discovering flights", 3)
        update(1)
        discovery_ready.set()
        assert continue_discovery.wait(5)
        progress.stop()
        update = progress.start("Confirming options", 2)
        update(1)
        confirmation_ready.set()
        assert continue_confirmation.wait(5)
        progress.stop()
        return SimpleNamespace(itineraries=lambda: [confirmed_pair(request)])

    client = app_for(
        runner, cache_dir=cache_dir, cache_ttl="30m", cache_enabled=False
    ).test_client()
    path = start_search(
        client, regions=[], countries=["PT"], airline_codes=["TP"], depart_after="17"
    )

    try:
        for ready, resume, phase, total in (
            (discovery_ready, continue_discovery, "Discovering flights", 3),
            (confirmation_ready, continue_confirmation, "Confirming options", 2),
        ):
            assert ready.wait(5), client.get(path).get_json()
            response = client.get(path)
            assert response.status_code == 200
            state = response.get_json()
            assert state["status"] == "running"
            assert (state["phase"], state["done"], state["total"]) == (phase, 1, total)
            resume.set()
    finally:
        continue_discovery.set()
        continue_confirmation.set()

    state = wait_for_final_state(client, path)
    assert state["status"] == "done", state
    [pair] = state["result"]["pairs"]
    assert pair["city"] == "Lisbon"
    assert pair["total"] == 190
    assert pair["outbound"]["segments"] == 1
    assert pair["outbound"]["legs"][0]["origin"] == "FRA"
    assert pair["return"]["legs"][0]["destination"] == "FRA"
    for field in ("booking_url", "outbound_url", "return_url"):
        assert pair[field].startswith("https://www.google.com/travel/flights")


def test_searches_keep_separate_outcomes_and_reject_bad_inputs_before_running():
    runner = Mock(
        side_effect=(
            SimpleNamespace(itineraries=list),
            RuntimeError("offline runner failed"),
        )
    )
    client = app_for(runner).test_client()

    first = start_search(client, regions=["europe"])
    first_state = wait_for_final_state(client, first)
    assert first_state["status"] == "done"
    assert first_state["result"]["pairs"] == []

    followup = start_search(client, regions=["europe"])
    assert first != followup
    error_state = wait_for_final_state(client, followup)
    assert error_state["status"] == "error"
    assert "offline runner failed" in error_state["error"]
    assert client.get(first).get_json() == first_state

    for invalid in (
        {"start": "not a date", "regions": ["europe"]},
        {"regions": ["europe"], "max_requests": 9},
    ):
        response = client.post("/api/searches", json=invalid)
        assert response.status_code == 400
        assert isinstance(response.get_json()["error"], str)
    assert runner.call_count == 2
