"""Offline server diagnostics through the normal browser command."""

import json
import logging
import re
import sys

import waitress
from fake_flights import fake_detail_results
from test_cli_golden import AIRPORTS, BASE_ARGS, FrozenDate
from test_confirm_more import LISBON, more_url
from test_web import start_search, wait_for_final_state

from flight_search import cli, fli_api, web
from flight_search.settings_file import config_path

TRANSPORT_PROBE = "simulated transport attempt"
READABLE_PROBE = (
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3} DEBUG +Transport +\| "
    + TRANSPORT_PROBE
    + "$"
)


def write_config(**options):
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f"{key} = {json.dumps(value)}\n" for key, value in options.items()),
        encoding="utf-8",
    )


def transport_probe(app, **kwargs):
    logging.getLogger("fli.search._tfs").debug(TRANSPORT_PROBE)


def test_web_debug_defaults_and_overrides(monkeypatch, capsys):
    monkeypatch.setattr(waitress, "serve", transport_probe)
    monkeypatch.setattr(cli, "date", FrozenDate)
    monkeypatch.setattr(cli, "load_airports", lambda include_small=False: AIRPORTS)

    assert cli.main([*BASE_ARGS, "--dry-run"]) == 0
    assert " DEBUG " not in capsys.readouterr().err
    assert cli.main([*BASE_ARGS, "--dry-run", "--debug"]) == 0
    weekend_debug = capsys.readouterr().err
    assert re.search(
        r"^\d{4}-\d{2}-\d{2} .* DEBUG +Search +\|", weekend_debug, re.MULTILINE
    )

    assert cli.main(["web"]) == 0
    assert re.search(READABLE_PROBE, capsys.readouterr().err, re.MULTILINE)

    for configured in (False, True):
        write_config(debug=configured)
        for flags, expected in (
            ([], configured),
            (["--debug"], True),
            (["--no-debug"], False),
        ):
            assert cli.main(["web", *flags]) == 0
            stderr = capsys.readouterr().err
            assert bool(re.search(READABLE_PROBE, stderr, re.MULTILINE)) is expected
            assert (TRANSPORT_PROBE in stderr) is expected


def test_web_search_logs_phases_and_actual_city_load_requests(
    monkeypatch, capsys, tmp_path
):
    write_config(home_airports="FRA", per_city=1, max_requests=200)
    monkeypatch.setattr(cli, "date", FrozenDate)
    monkeypatch.setattr(web, "date", FrozenDate)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    create_app = web.create_app

    def offline_app(*args, **kwargs):
        return create_app(
            *args, airport_loader=lambda *, include_small: AIRPORTS, **kwargs
        )

    monkeypatch.setattr(web, "create_app", offline_app)
    attempts = []

    def offline_detail(*args, **kwargs):
        # Simulate one retry inside transport, below the request budget.
        for _ in range(2):
            attempts.append(args[:3])
            logging.getLogger("fli.search._tfs").debug(TRANSPORT_PROBE)
        return fake_detail_results(*args, **kwargs)

    monkeypatch.setattr(fli_api, "detail_results", offline_detail)
    search_fields = {
        "start": "2027-03-05",
        "end": "2027-03-21",
        "depart_days": ["fri"],
        "return_days": ["sun"],
        "min_nights": 2,
        "max_nights": 2,
        "regions": [],
        "countries": ["PT"],
    }
    search_logs = []
    loads = []

    def search(client):
        path = start_search(client, **search_fields)
        state = wait_for_final_state(client, path)
        assert state["status"] == "done", state
        result = state["result"]
        assert len(result["pairs"]) == 1
        assert result["pairs"][0]["city"] == "Lisbon"
        return path, result["pending"][LISBON]["next_requests"]

    def load(client, path, expected_requests):
        before = len(attempts)
        response = client.post(more_url(path))
        assert response.status_code == 200, response.get_json()
        assert len(response.get_json()["pairs"]) == 2
        assert len(attempts) - before == 2 * expected_requests
        loads.append((expected_requests, capsys.readouterr().err))

    def serve(app, **kwargs):
        client = app.test_client()
        refused = client.post(
            "/api/searches", json={**search_fields, "max_requests": 10}
        )
        assert refused.status_code == 400, refused.get_json()
        assert "exceed the limit" in refused.get_json()["error"]
        assert not attempts
        path, planned_requests = search(client)
        assert planned_requests == 2
        search_logs.append(capsys.readouterr().err)
        load(client, path, planned_requests)

        warm_path, warm_planned_requests = search(client)
        assert warm_planned_requests == planned_requests
        search_logs.append(capsys.readouterr().err)
        load(client, warm_path, 0)

        # Make a real Cache diagnostic without writing to a user's cache.
        for record in tmp_path.rglob("*.json"):
            record.write_text("broken json", encoding="utf-8")
        search(client)
        search_logs.append(capsys.readouterr().err)

    monkeypatch.setattr(waitress, "serve", serve)
    assert cli.main(["web"]) == 0

    cold, warm, corrupt = search_logs
    for label in ("Discovery", "Search", "Confirmation", "Transport"):
        assert re.search(rf"\b{label}(?: \[\d+\])? +\|", cold), (label, cold)
    assert re.search(r"\bCache +\|", corrupt), corrupt
    assert re.search(r"\bConfirmation +\| .*\bcache\b", warm), warm
    browser_logs = "\n".join(
        line for line in cold.splitlines() if not re.search(r"\bDiscovery.* \|", line)
    )
    assert re.search(r"\bplan\b", browser_logs, re.IGNORECASE), cold
    assert re.search(
        r"\b(?:done|finished|complete|completed|completion)\b",
        browser_logs,
        re.IGNORECASE,
    ), cold
    for expected_requests, stderr in loads:
        [line] = [
            line
            for line in stderr.splitlines()
            if re.search(r"\b(?:load(?:ed|ing)?|more)\b", line, re.IGNORECASE)
            and re.search(r"\bLisbon\b", line, re.IGNORECASE)
            and "request" in line.lower()
        ]
        assert re.search(
            rf"\b(?:requests?\D{{0,8}}{expected_requests}|{expected_requests} (?:actual |network )?requests?)\b",
            line,
            re.IGNORECASE,
        ), line


def test_web_redirects_server_diagnostics_to_stderr(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(waitress, "serve", transport_probe)
    redirected = tmp_path / "stderr.txt"
    with (
        redirected.open("w", encoding="utf-8") as stream,
        monkeypatch.context() as patch,
    ):
        patch.setattr(sys, "stderr", stream)
        assert cli.main(["web", "--port", "9876"]) == 0

    output = capsys.readouterr()
    assert output.out == "Open http://127.0.0.1:9876 in your browser.\n"
    assert output.err == ""
    stderr = redirected.read_text(encoding="utf-8")
    assert "Open http://" not in stderr
    assert re.search(READABLE_PROBE, stderr, re.MULTILINE)
