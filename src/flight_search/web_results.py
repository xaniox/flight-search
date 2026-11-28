"""Project the confirmed weekend results used by both browser views."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import cache
from uuid import uuid4

from flight_search.airport_timezones import arrival_utc, departure_utc, stay_minutes
from flight_search.combine import FlightOption, direction_dict
from flight_search.config import SearchSettings
from flight_search.detail import OptionKey, eligible_options
from flight_search.links import attach_links, itinerary_url, leg_url
from flight_search.search import SearchResult

logger = logging.getLogger(__name__)


def _compatible_instants(arrival: int | None, departure: int | None) -> bool:
    return arrival is None or departure is None or departure >= arrival


def pair_results(result: SearchResult, settings: SearchSettings, top: int) -> dict:
    outbound_arrival = cache(arrival_utc)
    inbound_departure = cache(departure_utc)

    def compatible(outbound: FlightOption, inbound: FlightOption) -> bool:
        return _compatible_instants(
            outbound_arrival(outbound), inbound_departure(inbound)
        )

    itineraries = (
        result.itineraries(compatible=compatible)
        if isinstance(result, SearchResult)
        else result.itineraries()
    )
    pairs = itineraries[:top]
    attach_links(pairs, settings)
    return {
        "pairs": [
            {**pair.to_dict(), "stay_minutes": stay_minutes(pair.out, pair.ret)}
            for pair in pairs
        ]
    }


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

    def add_options(self, flights: list[FlightOption], *, outbound: bool) -> list[str]:
        timestamp_field = "arrival_utc" if outbound else "departure_utc"
        flight_timestamp = arrival_utc if outbound else departure_utc
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
                timestamp_field: flight_timestamp(flight),
            }
        return ids

    def add_outbound_group(self, group: dict) -> None:
        self.outbound_groups.append(group)
        for option_id in group["options"]:
            self._returns_by_outbound[option_id] = group["return_groups"]

    def booking_url(self, outbound_id: str, return_id: str) -> str | None:
        for group_id in self._returns_by_outbound.get(outbound_id, ()):
            if return_id in self.return_groups[group_id]["options"]:
                if not _compatible_instants(
                    self.options[outbound_id]["arrival_utc"],
                    self.options[return_id]["departure_utc"],
                ):
                    return None
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
                "options": projection.add_options(inbound, outbound=False),
            }
        if out_key not in out_groups:
            group = {
                "city": city.display,
                "country": city.country,
                "date": depart.isoformat(),
                "options": projection.add_options(outbound, outbound=True),
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
