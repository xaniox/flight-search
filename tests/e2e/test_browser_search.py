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


def money(text: str) -> float:
    return float(re.sub(r"[^\d,]", "", text).replace(",", "."))


def group_prices(group) -> list[float]:
    """Prices of every card of a city group, including those folded away."""
    texts = group.locator(".trip .trip-heading .price").evaluate_all(
        "nodes => nodes.map(node => node.textContent)"
    )
    return [money(text) for text in texts]


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


def open_filters(page: Page, app_url: str) -> None:
    page.goto(app_url)
    expect(page.get_by_role("button", name="Flüge suchen")).to_be_enabled()
    page.locator("summary", has_text="Weitere Suchfilter").click()


def test_empty_time_field_is_sent_as_no_bound(page: Page, app_url: str):
    open_filters(page, app_url)
    page.get_by_label("Hinflug ab", exact=True).fill("15:00")
    page.get_by_label("Rückflug ab", exact=True).fill("")

    with page.expect_request("**/api/searches") as posted:
        page.get_by_role("button", name="Flüge suchen").click()
    fields = json.loads(posted.value.post_data)

    assert fields["depart_after"] == "15:00"
    assert fields["return_depart_after"] is None


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


def open_outbound_tab(page: Page, app_url: str) -> None:
    search(page, app_url)
    page.get_by_role("tab", name="Hinflug zuerst").click()
    expect(page.locator("#outbounds .option").first).to_be_visible(timeout=2000)


def open_folded(group) -> None:
    more = group.locator("details.more")
    if more.count() and more.get_attribute("open") is None:
        more.locator(":scope > summary").click()


def option_totals(group) -> list[float]:
    texts = group.locator(".option").all_inner_texts()
    return [
        money(re.search(r"([\d.]+,\d{2})\s€\s*gesamt", text).group(1)) for text in texts
    ]


def option_deltas(group) -> list[str]:
    return normalised(group.locator(".option .delta").all_inner_texts())


DELTA = r"^\+[\d.]+,\d{2} €$"


def test_outbound_deltas_are_surcharges_against_the_cheapest_total(
    page: Page, app_url: str
):
    open_outbound_tab(page, app_url)
    groups = page.locator("#outbounds .city-group")

    assert groups.count() > 1
    for index in range(groups.count()):
        group = groups.nth(index)
        open_folded(group)
        options = group.locator(".option")
        expect(options.first.locator(".delta")).to_be_visible(timeout=2000)
        for text in options.all_inner_texts():
            assert re.search(r"€\s*gesamt", text), text
            assert re.search(r"\bab [\d.]+,\d{2}\s€\s*gesamt", text), text
        totals = option_totals(group)
        deltas = option_deltas(group)
        assert len(deltas) == len(totals)
        for delta in deltas:
            assert re.match(DELTA, delta), delta
        assert [money(delta) for delta in deltas] == pytest.approx(
            [total - min(totals) for total in totals]
        )
        assert deltas.count("+0,00 €") >= 1


def test_return_deltas_are_surcharges_against_the_cheapest_return(
    page: Page, app_url: str
):
    open_outbound_tab(page, app_url)
    outbound = page.locator("#outbounds .option").first
    outbound_price = money(
        re.search(r"([\d.]+,\d{2})\s€ Hinflug", outbound.inner_text()).group(1)
    )
    outbound.click()
    cards = page.locator("#returns > .trip")
    expect(cards.first.locator(".delta")).to_be_visible(timeout=2000)

    deltas = normalised(cards.locator(".delta").all_inner_texts())
    texts = cards.locator(".trip-heading").all_inner_texts()
    totals = [
        money(re.search(r"([\d.]+,\d{2})\s€\s*gesamt", text).group(1)) for text in texts
    ]
    assert len(deltas) == len(totals) > 1
    for delta in deltas:
        assert re.match(DELTA, delta), delta
    parts = [total - outbound_price for total in totals]
    assert [money(delta) for delta in deltas] == pytest.approx(
        [part - min(parts) for part in parts]
    )
    assert "+0,00 €" in deltas


def test_outbound_deltas_do_not_depend_on_the_sort_order(page: Page, app_url: str):
    open_outbound_tab(page, app_url)
    rome = city_group(page, "#outbounds", "Rome")
    open_folded(rome)
    expect(rome.locator(".option .delta").first).to_be_visible(timeout=2000)
    ascending = sorted(option_deltas(rome))

    page.get_by_label("Sortierung").select_option("price-desc")
    rome = city_group(page, "#outbounds", "Rome")
    open_folded(rome)
    expect(rome.locator(".option .delta").first).to_be_visible(timeout=2000)

    assert len(ascending) > 1
    assert sorted(option_deltas(rome)) == ascending


def test_return_panel_says_prices_are_sums_of_one_way_tickets(page: Page, app_url: str):
    open_outbound_tab(page, app_url)

    note = page.locator("#selected-context, #returns").filter(has_text="Einzeltickets")
    expect(note.first).to_be_visible(timeout=2000)


def normalised(texts: list[str]) -> list[str]:
    """Texts with the no-break space of the currency format turned into a blank."""
    return [text.replace("\xa0", " ").strip() for text in texts]


def last_state(responses: list) -> dict:
    """The newest finished search state the page polled."""
    return [r.json() for r in responses if r.ok][-1]


def watch_states(page: Page) -> list:
    responses: list = []
    page.on(
        "response",
        lambda r: (
            responses.append(r)
            if r.request.method == "GET"
            and re.search(r"/api/searches/[0-9a-f]+$", r.url)
            else None
        ),
    )
    return responses


@pytest.mark.parametrize(
    "app_url", [{"per_city": 1, "max_candidates": 2}], indirect=True
)
def test_cities_without_a_confirmed_pair_offer_to_load_theirs(page: Page, app_url: str):
    responses = watch_states(page)
    search(page, app_url)

    pending = last_state(responses)["result"]["pending"]
    groups = page.locator("#pairs .city-group")
    expect(groups.first).to_be_visible(timeout=2000)
    expect(groups).to_have_count(len(pending), timeout=2000)
    for index in range(groups.count()):
        expect(groups.nth(index).locator("button.more-btn")).to_have_count(1)
    empty = groups.filter(has_not=page.locator(".trip"))
    assert empty.count() > 0
    name = empty.first.locator(".city-head strong").inner_text()
    empty.first.locator("button.more-btn").click()

    loaded = city_group(page, "#pairs", name)
    expect(loaded.locator(".trip").first).to_be_attached(timeout=15_000)


@pytest.mark.parametrize("app_url", [{"max_candidates": 0}], indirect=True)
def test_nothing_confirmed_but_pending_still_shows_the_results(
    page: Page, app_url: str
):
    search(page, app_url)

    expect(page.locator("#pairs .city-group").first).to_be_visible(timeout=2000)
    expect(page.locator("#pairs button.more-btn").first).to_be_visible()


@ONE_PER_CITY
def test_every_outbound_row_says_ab_and_returns_do_not(page: Page, app_url: str):
    open_outbound_tab(page, app_url)

    texts = page.locator("#outbounds .option").all_text_contents()
    assert len(texts) > 1
    for text in texts:
        assert re.search(r"ab [\d.]+,\d{2}[\s\xa0]€ gesamt", text), text
    page.locator("#outbounds .option").first.click()
    totals = normalised(
        page.locator("#returns > .trip .pricebox small").all_inner_texts()
    )
    assert totals
    for total in totals:
        assert re.match(r"^[\d.]+,\d{2} € gesamt$", total), total


@ONE_PER_CITY
def test_selected_outbound_survives_loading_more_of_another_city(
    page: Page, app_url: str
):
    open_outbound_tab(page, app_url)
    groups = page.locator("#outbounds .city-group")
    names = [
        name.split(" · ")[0]
        for name in groups.locator(".city-head strong").all_inner_texts()
    ]
    index = next(i for i, name in enumerate(names) if i > 0 and name != "Rome")
    chosen_city = names[index]
    chosen = groups.nth(index).locator(".option").first
    label = chosen.locator(".top strong").inner_text()
    route = chosen.locator(".route").inner_text()
    chosen.click()
    expect(page.locator("#selected-context")).to_contain_text(route)
    rome = city_group(page, "#outbounds", "Rome")
    before = rome.locator(".option").count()

    rome.locator("button.more-btn").click()
    expect(rome.locator(".option")).not_to_have_count(before, timeout=15_000)

    same = (
        city_group(page, "#outbounds", chosen_city)
        .locator(".option")
        .filter(has=page.locator(".top strong", has_text=label))
    )
    expect(same.first).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#selected-context")).to_contain_text(route)


def pairs_card_count(page: Page) -> int:
    return page.locator("#pairs .trip").count()


@ONE_PER_CITY
def test_loading_state_survives_the_rerender_of_another_cities_answer(
    page: Page, app_url: str, delays: dict
):
    search(page, app_url)
    lisbon = city_group(page, "#pairs", "Lisbon")
    palma = city_group(page, "#pairs", "Palma")
    expect(lisbon.locator("button.more-btn")).to_have_count(1, timeout=2000)
    delays["LIS"] = [2.0]
    delays["PMI"] = [2.0]
    lisbon_cards = lisbon.locator(".trip").count()

    lisbon.locator("button.more-btn").click()
    page.wait_for_timeout(300)
    palma.locator("button.more-btn").click()
    expect(lisbon.locator(".trip")).not_to_have_count(lisbon_cards, timeout=15_000)

    # Palma's request is still queued behind Lisbon's on the server.
    button = palma.locator("button.more-btn")
    expect(button).to_be_disabled()
    expect(button).to_contain_text("Wird bestätigt")


@ONE_PER_CITY
def test_a_late_answer_does_not_replace_the_results_of_a_newer_search(
    page: Page, app_url: str, delays: dict
):
    search(page, app_url)
    lisbon = city_group(page, "#pairs", "Lisbon")
    expect(lisbon.locator("button.more-btn")).to_have_count(1, timeout=2000)
    delays["LIS"] = [3.0]

    with page.expect_response(
        lambda r: r.url.endswith("/more") and r.request.method == "POST",
        timeout=15_000,
    ) as late:
        lisbon.locator("button.more-btn").click()
        page.get_by_role("button", name="Flüge suchen").click()
        expect(page.locator("#results")).to_be_visible(timeout=15_000)
        fresh = pairs_card_count(page)
    assert late.value.ok
    page.wait_for_timeout(500)

    assert pairs_card_count(page) == fresh


@ONE_PER_CITY
def test_failed_load_more_resets_the_clicked_button_in_outbound_first(
    page: Page, app_url: str
):
    page.route(
        "**/cities/**/more",
        lambda route: route.fulfill(
            status=500,
            content_type="application/json",
            body=json.dumps({"error": "kaputt"}),
        ),
    )
    open_outbound_tab(page, app_url)
    button = more_button(page, "#outbounds", "Rome")
    expect(button).to_have_count(1, timeout=2000)

    button.click()

    expect(button).to_be_enabled(timeout=5000)
    expect(button).to_contain_text("kaputt")


@ONE_PER_CITY
def test_loading_disables_the_cities_button_in_both_tabs(
    page: Page, app_url: str, delays: dict
):
    posts: list = []
    page.on(
        "request",
        lambda r: (
            posts.append(r.url)
            if r.method == "POST" and r.url.endswith("/more")
            else None
        ),
    )
    search(page, app_url)
    pairs_button = more_button(page, "#pairs", "Lisbon")
    expect(pairs_button).to_have_count(1, timeout=2000)
    delays["LIS"] = [3.0]

    pairs_button.click()
    page.get_by_role("tab", name="Hinflug zuerst").click()
    twin = more_button(page, "#outbounds", "Lisbon")

    expect(twin).to_be_disabled(timeout=1000)
    expect(twin).to_contain_text("Wird bestätigt")
    twin.click(force=True, no_wait_after=True)
    page.wait_for_timeout(500)
    assert len(posts) <= 1, posts
