from types import SimpleNamespace
from unittest.mock import Mock

from test_web import app_for, start_search, wait_for_final_state


def test_browser_search_can_raise_the_configured_request_limit():
    runner = Mock(return_value=SimpleNamespace(itineraries=list))
    client = app_for(runner).test_client()

    assert client.get("/api/catalogs").get_json()["defaults"]["max_requests"] == 10

    path = start_search(client, regions=["europe"], max_requests=11)
    state = wait_for_final_state(client, path)

    assert state["status"] == "done", state
    runner.assert_called_once()
    assert runner.call_args.kwargs["budget"].limit == 11
    assert client.get("/api/catalogs").get_json()["defaults"]["max_requests"] == 10
