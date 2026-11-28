from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import waitress
from test_web import AIRPORTS, app_for, start_search, wait_for_final_state

from flight_search import cli, web

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def test_browser_cli_keeps_form_and_omitted_dates_current(monkeypatch):
    launched = date(2040, 1, 4)
    current = launched

    class ClockDate(date):
        @classmethod
        def today(cls):
            return current

    serve = Mock()
    runner = Mock(return_value=SimpleNamespace(itineraries=list))
    create_app = web.create_app

    def create_test_app(*args, **kwargs):
        return create_app(
            *args,
            **kwargs,
            search_runner=runner,
            airport_loader=lambda *, include_small: AIRPORTS,
        )

    monkeypatch.setattr(cli, "date", ClockDate)
    monkeypatch.setattr(web, "date", ClockDate)
    monkeypatch.setattr(web, "create_app", create_test_app)
    monkeypatch.setattr(waitress, "serve", serve)
    assert cli.main(["web"]) == 0
    client = serve.call_args.args[0].test_client()
    original = client.get("/api/catalogs").get_json()["defaults"]
    assert original["start"] == launched.isoformat()
    window = date.fromisoformat(original["end"]) - launched

    current = launched + timedelta(days=1)
    rolled = client.get("/api/catalogs").get_json()["defaults"]
    assert rolled["start"] == current.isoformat()
    assert rolled["end"] == (current + window).isoformat()

    path = start_search(
        client,
        regions=[],
        countries=["PT"],
        depart_days=WEEKDAYS,
        return_days=WEEKDAYS,
        min_nights=0,
        max_nights=0,
        max_requests=1000,
    )
    state = wait_for_final_state(client, path)
    assert state["status"] == "done", state
    [request] = runner.call_args.args
    assert request.pairs[0].depart == current
    assert request.pairs[-1].ret == current + window


def test_direct_browser_app_preserves_explicit_date_defaults(monkeypatch):
    client = app_for(Mock()).test_client()
    original = client.get("/api/catalogs").get_json()["defaults"]

    class LaterDate(date):
        @classmethod
        def today(cls):
            return date.fromisoformat(original["start"]) + timedelta(days=1)

    monkeypatch.setattr(web, "date", LaterDate)
    later = client.get("/api/catalogs").get_json()["defaults"]
    assert (later["start"], later["end"]) == (original["start"], original["end"])
