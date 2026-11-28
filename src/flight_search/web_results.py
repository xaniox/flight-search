"""Project confirmed weekend pairs to the browser response."""

from flight_search.config import SearchSettings
from flight_search.links import attach_links
from flight_search.search import SearchResult


def pair_results(result: SearchResult, settings: SearchSettings, top: int) -> dict:
    pairs = result.itineraries()[:top]
    attach_links(pairs, settings)
    return {"pairs": [pair.to_dict() for pair in pairs]}
