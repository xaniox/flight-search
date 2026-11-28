"""Layout and pointer interaction on the weekend search form."""

import pytest
from playwright.sync_api import Locator, Page, expect


@pytest.fixture
def desktop_form(page: Page, app_url: str) -> Page:
    page.set_viewport_size({"width": 1000, "height": 750})
    page.goto(app_url)
    expect(page.get_by_role("button", name="Flüge suchen")).to_be_enabled()
    return page


def bounds(control: Locator):
    box = control.bounding_box()
    assert box is not None, f"{control} has no visible bounds"
    return box


def test_dates_and_pickers_start_on_the_same_line(desktop_form: Page):
    page = desktop_form
    controls = {
        "Abflughäfen": page.locator("#home-picker summary"),
        "Von": page.get_by_label("Von", exact=True),
        "Bis": page.get_by_label("Bis", exact=True),
        "Ziele": page.locator("#destination-picker summary"),
        "Airlines": page.locator("#airline-picker summary"),
    }
    boxes = {label: bounds(control) for label, control in controls.items()}
    tops = {label: box["y"] for label, box in boxes.items()}
    assert max(tops.values()) - min(tops.values()) <= 1, tops

    single_line_heights = {
        label: boxes[label]["height"]
        for label in ("Abflughäfen", "Von", "Bis", "Airlines")
    }
    assert max(single_line_heights.values()) - min(single_line_heights.values()) <= 1, (
        single_line_heights
    )


def test_wrapped_destination_chip_leaves_space_to_its_right(desktop_form: Page):
    summary = desktop_form.locator("#destination-picker summary")
    chip = summary.get_by_text("Europa und angrenzende Länder", exact=True)
    assert chip.evaluate(
        """chip => {
            const text = document.createRange();
            text.selectNodeContents(chip);
            return text.getClientRects().length > 1;
        }"""
    ), "the default chip must actually wrap at this viewport width"
    summary_box, chip_box = bounds(summary), bounds(chip)
    space = summary_box["x"] + summary_box["width"] - chip_box["x"] - chip_box["width"]
    assert space >= 16, f"only {space:.1f}px to the right of the wrapped chip"


@pytest.mark.parametrize(
    ("picker", "search_name", "query", "option_name"),
    [
        ("home", "Flughäfen suchen", "FRA", "FRA"),
        ("destination", "Zielregionen und Länder suchen", "Italien", "Italien"),
        ("airline", "Airlines suchen", "LH", "LH · Lufthansa"),
    ],
)
def test_open_picker_search_box_and_choice_are_reachable(
    desktop_form: Page, picker: str, search_name: str, query: str, option_name: str
):
    page = desktop_form
    page.locator(f"#{picker}-picker summary").click()
    search = page.get_by_role("searchbox", name=search_name)
    box = bounds(search)
    for x in (box["x"] + 4, box["x"] + box["width"] / 2, box["x"] + box["width"] - 4):
        for y in (box["y"] + 4, box["y"] + box["height"] - 4):
            receives_pointer = search.evaluate(
                "(input, point) => document.elementFromPoint(...point) === input",
                [x, y],
            )
            assert receives_pointer, f"{search_name} is covered at ({x:.1f}, {y:.1f})"
    search.fill(query)
    option = page.get_by_role("checkbox", name=option_name)
    option.set_checked(not option.is_checked(), timeout=2000)


@pytest.mark.parametrize(
    "dismiss", ["selected chip", "outside", "another picker", "Escape"]
)
def test_dismissing_picker_releases_pointer_and_keeps_selection(
    desktop_form: Page, dismiss: str
):
    page = desktop_form
    picker = page.locator("#destination-picker")
    summary = picker.locator("summary")
    chip = summary.get_by_text("Europa und angrenzende Länder", exact=True)
    search = picker.locator("input[type=search]")
    summary.click()
    expect(search).to_be_focused()
    box = bounds(search)
    former_popup_point = [box["x"] + box["width"] / 2, box["y"] + box["height"] / 2]

    if dismiss == "selected chip":
        chip.click(timeout=2000)
    elif dismiss == "outside":
        page.get_by_role("heading", name="Wochenendsuche").click(timeout=2000)
    elif dismiss == "another picker":
        page.locator("#airline-picker summary").click(timeout=2000)
        expect(page.get_by_role("searchbox", name="Airlines suchen")).to_be_visible()
    else:
        search.press("Escape")

    expect(search).to_be_hidden(timeout=2000)
    expect(chip).to_be_visible()
    assert picker.evaluate(
        "(picker, point) => !picker.contains(document.elementFromPoint(...point))",
        former_popup_point,
    )


def test_double_click_on_open_airline_chip_leaves_picker_closed(desktop_form: Page):
    page = desktop_form
    picker = page.locator("#airline-picker")
    summary = picker.locator("summary")
    search = page.get_by_role("searchbox", name="Airlines suchen")
    summary.click()
    search.fill("OA")
    page.get_by_role("checkbox", name="OA · Olympic Air").check()
    chip = summary.get_by_text("OA", exact=True)

    chip.dblclick(timeout=2000)

    expect(search).to_be_hidden(timeout=2000)
    expect(chip).to_be_visible()
