from types import SimpleNamespace

from test_web import app_for, start_search, wait_for_final_state


def test_completed_browser_search_reports_incomplete_discovery():
    def runner(request, *, cache, budget, progress):
        progress.discovered(["Discovery batch for Sunday failed"])
        return SimpleNamespace(itineraries=list)

    client = app_for(runner).test_client()
    path = start_search(client, regions=["europe"])
    state = wait_for_final_state(client, path)

    assert state["status"] == "done", state
    assert state["result"]["pairs"] == []
    assert any("incomplete" in warning.lower() for warning in state["warnings"]), state
