from typing import get_type_hints

from flight_search.detail import confirm_options
from flight_search.discover import run_discovery


def test_confirm_options_progress_hint_matches_run_discovery():
    detail_hint = get_type_hints(confirm_options)["progress"]
    discover_hint = get_type_hints(run_discovery)["progress"]

    assert detail_hint == discover_hint
