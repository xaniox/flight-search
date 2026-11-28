"""Search form persistence through reloads and server restarts."""

from datetime import date, timedelta
from threading import Thread

import pytest
from conftest import AIRPORTS, _defaults
from playwright.sync_api import Page, expect
from werkzeug.serving import make_server

from flight_search.web import create_app


def submit_button(page: Page):
    return page.get_by_role("button", name="Flüge suchen")


def open_form(page: Page, url: str) -> None:
    page.goto(url)
    expect(submit_button(page)).to_be_enabled()


def advanced_filters(page: Page) -> None:
    page.locator("summary", has_text="Weitere Suchfilter").click()


def form_values(page: Page, name: str) -> list[str]:
    return page.locator("#search").evaluate(
        "(form, name) => new FormData(form).getAll(name)", name
    )


def watch_search_requests(page: Page) -> list:
    requests = []
    page.on(
        "request",
        lambda request: (
            requests.append(request) if "/api/searches" in request.url else None
        ),
    )
    return requests


@pytest.mark.parametrize(
    "app_url", [{"depart_after": "09:00", "allow_codeshare": True}], indirect=True
)
def test_unsent_edits_and_empty_selections_survive_reload(page: Page, app_url: str):
    searches = watch_search_requests(page)
    open_form(page, app_url)
    advanced_filters(page)
    page.get_by_label("Hinflug ab leeren").click()
    page.get_by_label("Rückflug ab", exact=True).fill("15:35")
    page.get_by_label("Codeshares erlauben").uncheck()
    page.locator("[name=depart_days][value=fri]").uncheck()
    page.locator("[name=return_days][value=sat]").check()
    page.locator("[name=return_days][value=sun]").uncheck()
    page.get_by_label("Mind. Nächte").fill("1")
    page.get_by_label("Max. Nächte").fill("4")
    page.get_by_label("Max. Anfragen").fill("42")

    page.locator("#home-picker summary").click()
    page.locator("[name=home][value=FRA]").uncheck()
    page.locator("#destination-picker summary").click()
    page.locator('[name=destination][value="region:europe"]').uncheck()

    page.reload()
    expect(submit_button(page)).to_be_enabled()

    expect(page.locator("#home-picker summary")).to_have_text("Abflughäfen wählen")
    expect(page.locator("#destination-picker summary")).to_have_text(
        "Region oder Land wählen"
    )
    assert form_values(page, "home") == []
    assert form_values(page, "destination") == []
    assert form_values(page, "depart_days") == []
    assert form_values(page, "return_days") == ["sat"]
    expect(page.get_by_label("Hinflug ab", exact=True)).to_have_value("")
    expect(page.get_by_label("Rückflug ab", exact=True)).to_have_value("15:35")
    expect(page.get_by_label("Codeshares erlauben")).not_to_be_checked()
    expect(page.get_by_label("Mind. Nächte")).to_have_value("1")
    expect(page.get_by_label("Max. Nächte")).to_have_value("4")
    expect(page.get_by_label("Max. Anfragen")).to_have_value("42")
    assert not searches


def test_restored_picker_choices_are_sent_without_restoring_transient_ui(
    page: Page, app_url: str
):
    searches = watch_search_requests(page)
    open_form(page, app_url)
    page.locator("#home-picker summary").click()
    page.locator("[name=home][value=FRA]").uncheck()
    page.locator("[name=home][value=BCN]").check()
    page.locator("#destination-picker summary").click()
    page.locator('[name=destination][value="region:europe"]').uncheck()
    page.get_by_role("searchbox", name="Zielregionen und Länder suchen").fill("Italien")
    page.locator('[name=destination][value="country:IT"]').check()
    page.locator("#airline-picker summary").click()
    page.get_by_role("searchbox", name="Airlines suchen").fill("LH")
    page.locator("[name=airline_codes][value=LH]").check()
    page.locator("#airline-picker summary").click()

    page.route(
        "**/api/searches",
        lambda route: route.fulfill(status=400, json={"error": "Testantwort"}),
    )
    submit_button(page).click()
    expect(page.get_by_role("status")).to_contain_text("Testantwort")
    assert len(searches) == 1

    page.reload()
    expect(submit_button(page)).to_be_enabled()

    expect(page.locator("#home-picker summary")).to_have_text("BCN")
    expect(page.locator("#destination-picker summary")).to_have_text("Italien")
    expect(page.locator("#airline-picker summary")).to_have_text("LH")
    expect(page.locator("#status")).to_be_hidden()
    expect(page.locator("#results")).to_be_hidden()
    expect(page.locator("#airline-picker input[type=search]")).to_have_value("")
    assert len(searches) == 1

    submit_button(page).click()
    expect(page.get_by_role("status")).to_contain_text("Testantwort")
    assert len(searches) == 2
    assert searches[-1].post_data_json["home"] == ["BCN"]
    assert searches[-1].post_data_json["airline_codes"] == ["LH"]
    assert searches[-1].post_data_json["regions"] == []
    assert searches[-1].post_data_json["countries"] == ["IT"]


@pytest.fixture
def restartable_server():
    def no_search(*args, **kwargs):
        raise AssertionError("The form must not start a search")

    def replace_app(**changes):
        nonlocal app
        app = create_app(
            _defaults(**changes),
            configured_regions={},
            search_runner=no_search,
            airport_loader=lambda *, include_small: AIRPORTS,
            cache_enabled=False,
        )

    app = None
    replace_app()
    server = make_server(
        "127.0.0.1", 0, lambda env, start: app(env, start), threaded=True
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", replace_app
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_restarted_server_restores_dates_and_uses_its_current_date_constraints(
    page: Page, restartable_server
):
    url, restart = restartable_server
    searches = watch_search_requests(page)
    open_form(page, url)
    start = page.get_by_label("Von", exact=True)
    end = page.get_by_label("Bis", exact=True)
    initial_start = date.fromisoformat(start.input_value())
    saved_start = (initial_start + timedelta(days=1)).isoformat()
    saved_end = (initial_start + timedelta(days=8)).isoformat()
    start.fill(saved_start)
    end.fill(saved_end)
    new_min = (initial_start + timedelta(days=3)).isoformat()
    new_end = (initial_start + timedelta(days=18)).isoformat()
    restart(start=new_min, end=new_end)

    page.reload()
    expect(submit_button(page)).to_be_enabled()

    expect(start).to_have_value(saved_start)
    expect(end).to_have_value(saved_end)
    expect(start).to_have_attribute("min", new_min)
    expect(end).to_have_attribute("min", new_min)
    assert start.evaluate("field => field.validity.rangeUnderflow")
    submit_button(page).click()
    assert not searches

    fresh_context = page.context.browser.new_context()
    try:
        fresh_page = fresh_context.new_page()
        open_form(fresh_page, url)
        expect(fresh_page.get_by_label("Von", exact=True)).to_have_value(new_min)
        expect(fresh_page.get_by_label("Bis", exact=True)).to_have_value(new_end)
    finally:
        fresh_context.close()


def test_unavailable_storage_still_allows_using_the_form(page: Page, app_url: str):
    page.add_init_script(
        """
        window.storageAttempts = 0;
        Object.defineProperty(window, "localStorage", {
            get: () => {
                window.storageAttempts++;
                throw new DOMException("Storage is blocked", "SecurityError");
            }
        });
        """
    )
    open_form(page, app_url)
    advanced_filters(page)
    page.get_by_label("Max. Anfragen").fill("42")
    page.route(
        "**/api/searches",
        lambda route: route.fulfill(status=400, json={"error": "Testantwort"}),
    )
    with page.expect_request("**/api/searches") as request:
        submit_button(page).click()

    assert request.value.post_data_json["max_requests"] == 42
    assert page.evaluate("window.storageAttempts") > 0
