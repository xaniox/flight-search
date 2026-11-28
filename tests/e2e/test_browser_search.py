"""The browser search end to end: form, both result views, sorting, time fields."""

from __future__ import annotations

import json
import re

from playwright.sync_api import Page, expect


def search(page: Page, app_url: str) -> None:
    page.goto(app_url)
    submit = page.get_by_role("button", name="Flüge suchen")
    expect(submit).to_be_enabled()
    submit.click()
    expect(page.locator("#results")).to_be_visible(timeout=15_000)


def prices(page: Page, selector: str) -> list[float]:
    texts = page.locator(selector).all_inner_texts()
    return [float(re.sub(r"[^\d,]", "", text).replace(",", ".")) for text in texts]


def test_search_shows_pairs_with_details(page: Page, app_url: str):
    search(page, app_url)

    trips = page.locator("#pairs > .trip")
    expect(trips.first).to_be_visible()
    expect(page.locator("#context")).to_contain_text("Flugpaar")
    trips.first.locator("summary").click()
    expect(trips.first.get_by_role("link", name="Hinflug öffnen")).to_be_visible()


def test_outbound_first_offers_returns_for_the_chosen_outbound(
    page: Page, app_url: str
):
    search(page, app_url)

    page.get_by_role("tab", name="Hinflug zuerst").click()
    outbounds = page.locator("#outbounds > .option")
    expect(outbounds.nth(1)).to_be_visible()
    second = outbounds.nth(1)
    route = second.locator(".route").inner_text()
    second.click()

    expect(second).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#selected-context")).to_contain_text(route)
    expect(page.locator("#returns > .trip").first).to_be_visible()


def test_sorting_orders_pairs_by_price(page: Page, app_url: str):
    search(page, app_url)
    selector = "#pairs > .trip .trip-heading .price"

    ascending = prices(page, selector)
    page.get_by_label("Sortierung").select_option("price-desc")
    descending = prices(page, selector)

    assert len(ascending) > 1
    assert ascending == sorted(ascending)
    assert descending == sorted(ascending, reverse=True)


def test_empty_time_field_is_sent_as_no_bound(page: Page, app_url: str):
    page.goto(app_url)
    expect(page.get_by_role("button", name="Flüge suchen")).to_be_enabled()
    page.locator("summary", has_text="Weitere Suchfilter").click()
    page.get_by_label("Hinflug ab", exact=True).fill("15:00")
    page.get_by_label("Rückflug ab", exact=True).fill("")

    with page.expect_request("**/api/searches") as posted:
        page.get_by_role("button", name="Flüge suchen").click()
    fields = json.loads(posted.value.post_data)

    assert fields["depart_after"] == "15:00"
    assert fields["return_depart_after"] is None


def open_filters(page: Page, app_url: str) -> None:
    page.goto(app_url)
    expect(page.get_by_role("button", name="Flüge suchen")).to_be_enabled()
    page.locator("summary", has_text="Weitere Suchfilter").click()


def test_clear_button_empties_a_time_field_and_sends_no_bound(page: Page, app_url: str):
    open_filters(page, app_url)
    field = page.locator("label", has=page.locator("input[name=depart_after]"))
    time_input = page.locator("input[name=depart_after]")
    clear = page.get_by_role("button", name="Hinflug ab leeren")
    time_input.fill("15:00")
    expect(clear).to_be_visible(timeout=2000)

    clear.click()

    expect(time_input).to_have_value("")
    expect(field.get_by_text("beliebig")).to_be_visible(timeout=2000)
    expect(clear).to_be_hidden(timeout=2000)
    with page.expect_request("**/api/searches") as posted:
        page.get_by_role("button", name="Flüge suchen").click()
    assert json.loads(posted.value.post_data)["depart_after"] is None


def test_clear_button_resets_partially_deleted_native_time_field(
    page: Page, app_url: str
):
    open_filters(page, app_url)
    field = page.get_by_label("Rückflug ab", exact=True)
    clear = page.get_by_role("button", name="Rückflug ab leeren")
    field.fill("16:32")
    field.click(position={"x": 16, "y": 21})
    page.keyboard.press("Backspace")

    expect(field).to_have_value("")
    assert field.evaluate("input => input.validity.badInput")

    clear.click()

    expect(field).to_have_value("")
    assert not field.evaluate("input => input.validity.badInput")
    with page.expect_request("**/api/searches") as posted:
        page.get_by_role("button", name="Flüge suchen").click()
    assert json.loads(posted.value.post_data)["return_depart_after"] is None


def test_empty_time_field_shows_any_time(page: Page, app_url: str):
    open_filters(page, app_url)
    field = page.locator("label", has=page.locator("input[name=return_arrive_before]"))
    time_input = page.locator("input[name=return_arrive_before]")
    clear = page.get_by_role("button", name="Rückkehr bis leeren")
    time_input.fill("")
    time_input.blur()

    expect(field.get_by_text("beliebig")).to_be_visible(timeout=2000)
    expect(clear).to_be_hidden(timeout=2000)

    time_input.fill("20:30")

    expect(field.get_by_text("beliebig")).to_be_hidden(timeout=2000)
    expect(clear).to_be_visible(timeout=2000)
