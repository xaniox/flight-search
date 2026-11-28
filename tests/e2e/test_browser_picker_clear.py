"""Search clearing and selected-option removal in browser pickers."""

import pytest
from playwright.sync_api import Page, expect

PICKERS = (
    ("home-picker", "Flughäfen suchen", "home", "FRA", "FRA entfernen", False),
    (
        "destination-picker",
        "Zielregionen und Länder suchen",
        "destination",
        "region:europe",
        "Europa und angrenzende Länder entfernen",
        True,
    ),
    (
        "airline-picker",
        "Airlines suchen",
        "airline_codes",
        "LH",
        "LH entfernen",
        True,
    ),
)


@pytest.mark.parametrize(
    ("picker_id", "search_name", "option_value"),
    [
        ("home-picker", "Flughäfen suchen", "LIS"),
        ("destination-picker", "Zielregionen und Länder suchen", "country:IT"),
        ("airline-picker", "Airlines suchen", "A3"),
    ],
)
def test_search_clear_x_restores_options_without_closing_or_changing_selection(
    page: Page, app_url: str, picker_id: str, search_name: str, option_value: str
):
    page.goto(app_url)
    picker = page.locator(f"#{picker_id}")
    picker.locator("summary").click()
    search = page.get_by_role("searchbox", name=search_name)
    search.fill("no matching choice")
    expect(picker.locator(".picker-empty")).to_be_visible()

    # Click the native X at the right edge inside the active search field.
    box = search.bounding_box()
    assert box is not None
    page.mouse.click(box["x"] + box["width"] - 18, box["y"] + box["height"] / 2)

    expect(search).to_have_value("")
    expect(picker).to_have_attribute("open", "")
    expect(
        picker.locator(f'input[type="checkbox"][value="{option_value}"]')
    ).to_be_visible()
    if picker_id == "home-picker":
        expect(picker.locator('[name="home"][value="FRA"]')).to_be_checked()
    elif picker_id == "destination-picker":
        expect(
            picker.locator('[name="destination"][value="region:europe"]')
        ).to_be_checked()
    else:
        expect(picker.locator('[name="airline_codes"][value="LH"]')).not_to_be_checked()


@pytest.mark.parametrize(
    ("picker_id", "search_name"),
    [
        ("home-picker", "Flughäfen suchen"),
        ("destination-picker", "Zielregionen und Länder suchen"),
        ("airline-picker", "Airlines suchen"),
    ],
)
def test_search_clear_control_is_named_and_keyboard_activatable(
    page: Page, app_url: str, picker_id: str, search_name: str
):
    page.goto(app_url)
    picker = page.locator(f"#{picker_id}")
    picker.locator("summary").click()
    search = page.get_by_role("searchbox", name=search_name)
    search.fill("no matching choice")
    clear = picker.get_by_role("button", name="Suchtext leeren", exact=True)
    expect(clear).to_be_visible()

    if page.context.browser.browser_type.name == "webkit":
        assert clear.evaluate("element => element.tabIndex") == 0
        clear.focus()
    else:
        search.press("Tab")
    expect(clear).to_be_focused()
    page.keyboard.press("Enter")

    expect(search).to_have_value("")
    expect(picker.locator(".picker-empty")).to_be_hidden()
    expect(picker).to_have_attribute("open", "")


@pytest.mark.parametrize(
    (
        "picker_id",
        "search_name",
        "field_name",
        "value",
        "remove_name",
        "initially_open",
    ),
    PICKERS,
)
def test_selected_chip_remove_updates_checkbox_request_and_reload(
    page: Page,
    app_url: str,
    picker_id: str,
    search_name: str,
    field_name: str,
    value: str,
    remove_name: str,
    initially_open: bool,
):
    page.goto(app_url)
    picker = page.locator(f"#{picker_id}")
    if field_name == "airline_codes":
        picker.locator("summary").click()
        page.get_by_role("searchbox", name=search_name).fill("LH")
        picker.locator('[name="airline_codes"][value="LH"]').check()
    elif initially_open:
        picker.locator("summary").click()

    remove = page.get_by_role("button", name=remove_name, exact=True)
    expect(remove).to_be_visible()
    remove.click()

    expect(
        picker.locator(f'[name="{field_name}"][value="{value}"]')
    ).not_to_be_checked()
    expect(picker.locator("summary")).not_to_contain_text(value)
    if initially_open:
        expect(picker).to_have_attribute("open", "")
        picker.locator("summary").focus()
        page.keyboard.press("Escape")
    else:
        expect(picker).not_to_have_attribute("open", "")
    expect(remove).to_have_count(0)

    page.route(
        "**/api/searches",
        lambda route: route.fulfill(status=400, json={"error": "Testantwort"}),
    )
    expect(page.get_by_role("button", name="Flüge suchen")).to_be_enabled()
    with page.expect_request("**/api/searches") as request:
        page.get_by_role("button", name="Flüge suchen").click()
    submitted = request.value.post_data_json
    submitted_values = (
        submitted[field_name]
        if field_name in submitted
        else (
            [f"region:{region}" for region in submitted["regions"]]
            + [f"country:{country}" for country in submitted["countries"]]
        )
    )
    assert value not in submitted_values

    page.reload()
    expect(page.get_by_role("button", name="Flüge suchen")).to_be_enabled()
    expect(page.locator(f"#{picker_id} summary")).not_to_contain_text(value)
    expect(
        page.locator(f'#{picker_id} [name="{field_name}"][value="{value}"]')
    ).not_to_be_checked()
