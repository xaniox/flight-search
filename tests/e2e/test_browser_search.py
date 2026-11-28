"""The browser search end to end: form, both result views, sorting, time fields."""

from __future__ import annotations

import json
import re
from urllib.parse import urljoin

import pytest
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


def group_prices(group) -> list[float]:
    """Prices of every card of a city group, including those folded away."""
    texts = group.locator(".trip .trip-heading .price").evaluate_all(
        "nodes => nodes.map(node => node.textContent)"
    )
    return [float(re.sub(r"[^\d,]", "", text).replace(",", ".")) for text in texts]


MORE_SUMMARY = r"^\d+ weitere · .+€$"
ONE_PER_CITY = pytest.mark.parametrize("app_url", [{"per_city": 1}], indirect=True)


def city_group(page: Page, panel: str, city: str):
    return page.locator(f"{panel} .city-group").filter(
        has=page.locator(".city-head strong", has_text=city)
    )


def test_search_shows_pairs_with_details(page: Page, app_url: str):
    search(page, app_url)

    trips = page.locator("#pairs .trip")
    expect(trips.first).to_be_visible()
    expect(page.locator("#context")).to_contain_text("Flugpaar")
    trips.first.locator(":scope > summary").click()
    expect(trips.first.get_by_role("link", name="Hinflug öffnen")).to_be_visible()


def test_outbound_first_offers_returns_for_the_chosen_outbound(
    page: Page, app_url: str
):
    search(page, app_url)

    page.get_by_role("tab", name="Hinflug zuerst").click()
    outbounds = page.locator("#outbounds .option")
    expect(outbounds.nth(1)).to_be_visible()
    second = outbounds.nth(1)
    route = second.locator(".route").inner_text()
    second.click()

    expect(second).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#selected-context")).to_contain_text(route)
    expect(page.locator("#returns > .trip").first).to_be_visible()


def test_sorting_orders_cards_inside_groups_and_groups_by_first_card(
    page: Page, app_url: str
):
    search(page, app_url)
    groups = page.locator("#pairs .city-group")
    expect(groups.first).to_be_visible(timeout=2000)

    def snapshot():
        return [group_prices(groups.nth(index)) for index in range(groups.count())]

    ascending = snapshot()
    page.get_by_label("Sortierung").select_option("price-desc")
    descending = snapshot()

    assert len(ascending) > 1
    for group in ascending:
        assert group == sorted(group)
    firsts = [group[0] for group in ascending]
    assert firsts == sorted(firsts)
    for group in descending:
        assert group == sorted(group, reverse=True)
    firsts = [group[0] for group in descending]
    assert firsts == sorted(firsts, reverse=True)


@ONE_PER_CITY
def test_pairs_are_grouped_by_city_with_the_rest_folded_away(page: Page, app_url: str):
    search(page, app_url)

    groups = page.locator("#pairs .city-group")
    expect(groups.first).to_be_visible(timeout=2000)
    expect(page.locator("#context")).to_have_text("7 Flugpaare in 4 Städten")
    names = groups.locator(".city-head strong").all_inner_texts()
    assert sorted(name.split(" · ")[0] for name in names) == [
        "Barcelona",
        "Lisbon",
        "Palma",
        "Rome",
    ]
    for index in range(groups.count()):
        expect(groups.nth(index).locator(".group-list > .trip")).to_have_count(
            1, timeout=2000
        )

    rome = city_group(page, "#pairs", "Rome")
    more = rome.locator("details.more")
    expect(more).to_have_count(1, timeout=2000)
    expect(more.locator(":scope > summary")).to_have_text(re.compile(MORE_SUMMARY))
    expect(more.locator(":scope > summary")).to_contain_text("3 weitere")
    expect(more.locator(".trip").first).to_be_hidden()
    more.locator(":scope > summary").click()
    expect(more.locator(".trip")).to_have_count(3)
    expect(more.locator(".trip").first).to_be_visible()
    expect(city_group(page, "#pairs", "Lisbon").locator("details.more")).to_have_count(
        0
    )


@ONE_PER_CITY
def test_outbound_groups_fold_extra_options_and_still_show_returns(
    page: Page, app_url: str
):
    search(page, app_url)

    page.get_by_role("tab", name="Hinflug zuerst").click()
    groups = page.locator("#outbounds .city-group")
    expect(groups.first).to_be_visible(timeout=2000)
    for index in range(groups.count()):
        expect(groups.nth(index).locator(".group-list > .option")).to_have_count(
            1, timeout=2000
        )

    rome = city_group(page, "#outbounds", "Rome")
    more = rome.locator("details.more")
    expect(more.locator(":scope > summary")).to_have_text(
        re.compile(MORE_SUMMARY), timeout=2000
    )
    expect(more.locator(":scope > summary")).to_contain_text("3 weitere")
    more.locator(":scope > summary").click()
    expect(more.locator(".option")).to_have_count(3)
    folded = more.locator(".option").first
    expect(folded).to_be_visible()
    folded.click()

    expect(folded).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#returns > .trip").first).to_be_visible()


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


MORE_BUTTON = r"^\d+ weitere laden"


def more_button(page: Page, panel: str, city: str):
    return city_group(page, panel, city).locator("button.more-btn")


@ONE_PER_CITY
def test_more_button_summarises_the_unconfirmed_candidates(page: Page, app_url: str):
    search(page, app_url)

    groups = page.locator("#pairs .city-group")
    expect(groups.first).to_be_visible(timeout=2000)
    for index in range(groups.count()):
        button = groups.nth(index).locator("button.more-btn")
        expect(button).to_have_count(1, timeout=2000)
        expect(button).to_have_text(re.compile(MORE_BUTTON))
        expect(button).to_contain_text("offen")
        expect(button).to_contain_text("geschätzt")
        expect(button).to_contain_text("Anfragen")
        expect(button).to_contain_text("€")


@ONE_PER_CITY
def test_more_button_confirms_more_pairs_of_that_city(page: Page, app_url: str):
    search(page, app_url)
    rome = city_group(page, "#pairs", "Rome")
    expect(rome).to_have_count(1, timeout=2000)
    button = rome.locator("button.more-btn")
    expect(button).to_have_count(1, timeout=2000)
    trips = rome.locator(".trip")
    before = trips.count()
    group_count = page.locator("#pairs .city-group").count()

    with page.expect_request(
        lambda request: (
            re.search(r"/api/searches/[^/]+/cities/[^/]+/more$", request.url)
            is not None
            and request.method == "POST"
        )
    ):
        button.click()

    expect(trips).not_to_have_count(before, timeout=15_000)
    assert trips.count() > before
    expect(rome.locator("details.more")).to_have_attribute("open", "", timeout=2000)
    expect(rome.locator(".trip").last).to_be_visible(timeout=2000)
    assert page.locator("#pairs .city-group").count() == group_count
    if button.count():
        expect(button).to_have_text(re.compile(MORE_BUTTON))


@ONE_PER_CITY
def test_more_button_in_outbound_first_loads_more_options(page: Page, app_url: str):
    search(page, app_url)
    page.get_by_role("tab", name="Hinflug zuerst").click()
    rome = city_group(page, "#outbounds", "Rome")
    button = rome.locator("button.more-btn")
    expect(button).to_have_count(1, timeout=2000)
    expect(button).to_have_text(re.compile(MORE_BUTTON))
    before = rome.locator(".option").count()

    button.click()

    expect(rome.locator(".option")).not_to_have_count(before, timeout=15_000)
    assert rome.locator(".option").count() > before
    expect(page.get_by_role("tab", name="Hinflug zuerst")).to_have_attribute(
        "aria-selected", "true"
    )


@ONE_PER_CITY
def test_booking_link_of_a_newly_loaded_flight_resolves(page: Page, app_url: str):
    search(page, app_url)
    page.get_by_role("tab", name="Hinflug zuerst").click()
    rome = city_group(page, "#outbounds", "Rome")
    button = rome.locator("button.more-btn")
    expect(button).to_have_count(1, timeout=2000)
    before = rome.locator(".option").count()
    button.click()
    expect(rome.locator(".option")).not_to_have_count(before, timeout=15_000)

    rome.locator(".option").last.click()

    first_return = page.locator("#returns > .trip").first
    first_return.locator(":scope > summary").click()
    link = first_return.get_by_role("link", name="Reise bei Google Flights öffnen")
    expect(link).to_be_visible(timeout=2000)
    href = link.evaluate("node => node.getAttribute('href')")
    assert "/booking?" in href
    response = page.request.get(urljoin(page.url, href), max_redirects=0)
    assert response.status == 302
