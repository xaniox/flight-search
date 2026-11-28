"""Project the confirmed weekend results used by both browser views."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import cache
from uuid import uuid4

from flight_search.combine import FlightOption, direction_dict
from flight_search.config import SearchSettings
from flight_search.detail import OptionKey, eligible_options
from flight_search.links import attach_links, itinerary_url, leg_url
from flight_search.search import SearchResult

logger = logging.getLogger(__name__)


def pair_results(result: SearchResult, settings: SearchSettings, top: int) -> dict:
    pairs = result.itineraries()[:top]
    attach_links(pairs, settings)
    return {"pairs": [pair.to_dict() for pair in pairs]}


@dataclass(slots=True)
class OutboundProjection:
    settings: SearchSettings
    options: dict[str, dict] = field(default_factory=dict)
    outbound_groups: list[dict] = field(default_factory=list)
    return_groups: dict[str, dict] = field(default_factory=dict)
    _flights: dict[str, FlightOption] = field(default_factory=dict)
    _returns_by_outbound: dict[str, list[str]] = field(default_factory=dict)

    def payload(self) -> dict:
        return {
            "options": self.options,
            "outbound_groups": self.outbound_groups,
            "return_groups": self.return_groups,
        }

    def add_options(self, flights: list[FlightOption]) -> list[str]:
        ids = []
        for flight in flights:
            option_id = uuid4().hex
            ids.append(option_id)
            self._flights[option_id] = flight
            url = None
            try:
                url = leg_url(flight, self.settings)
            except Exception:
                logger.debug("Could not create one-way booking link", exc_info=True)
            self.options[option_id] = {
                **direction_dict(flight),
                "booking_url": url,
            }
        return ids

    def add_outbound_group(self, group: dict) -> None:
        self.outbound_groups.append(group)
        for option_id in group["options"]:
            self._returns_by_outbound[option_id] = group["return_groups"]

    def booking_url(self, outbound_id: str, return_id: str) -> str | None:
        for group_id in self._returns_by_outbound.get(outbound_id, ()):
            if return_id in self.return_groups[group_id]["options"]:
                return itinerary_url(
                    self._flights[outbound_id], self._flights[return_id], self.settings
                )
        return None


def project_outbound_choices(result: SearchResult) -> OutboundProjection:
    """Index each filtered flight once and connect valid city/date groups."""
    request = result.request
    projection = OutboundProjection(request.settings)
    out_groups: dict[OptionKey, dict] = {}
    return_ids: dict[OptionKey, str] = {}

    @cache
    def filtered(key: OptionKey) -> list[FlightOption]:
        return eligible_options(
            key,
            result.options,
            depart_window=request.depart_window,
            return_window=request.return_window,
            airlines=request.airlines,
            allow_codeshare=request.allow_codeshare,
        )

    for candidate in result.shortlist:
        city = candidate.city
        depart, ret = candidate.pair.depart, candidate.pair.ret
        out_key: OptionKey = (city.key, depart, "out")
        return_key: OptionKey = (city.key, ret, "ret")
        outbound = filtered(out_key)
        inbound = filtered(return_key)
        if not outbound or not inbound:
            continue
        if return_key not in return_ids:
            group_id = uuid4().hex
            return_ids[return_key] = group_id
            projection.return_groups[group_id] = {
                "date": ret.isoformat(),
                "options": projection.add_options(inbound),
            }
        if out_key not in out_groups:
            group = {
                "city": city.display,
                "country": city.country,
                "date": depart.isoformat(),
                "options": projection.add_options(outbound),
                "return_groups": [],
            }
            out_groups[out_key] = group
            projection.add_outbound_group(group)
        return_group_id = return_ids[return_key]
        return_groups = out_groups[out_key]["return_groups"]
        if return_group_id not in return_groups:
            return_groups.append(return_group_id)
    return projection


def outbound_choices(result: SearchResult) -> dict:
    return project_outbound_choices(result).payload()
