from typing import get_type_hints

from flight_search.detail import evaluate_candidates
from flight_search.discover import run_discovery


def test_evaluate_candidates_progress_hint_matches_run_discovery():
    detail_hint = get_type_hints(evaluate_candidates)["progress"]
    discover_hint = get_type_hints(run_discovery)["progress"]

    assert detail_hint == discover_hint
