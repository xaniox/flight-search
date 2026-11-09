"""Google Flights deep links for confirmed itineraries.

The links are built offline from the itinerary's airports, dates, airlines and
flight numbers, using ``fli``'s deterministic ``tfs`` token encoder. No extra
HTTP request is involved.

A confirmed row is two separate one-way tickets. The primary ``booking_url``
encodes both legs as one two-segment itinerary (Google renders open-jaw
correctly, with different return airports). The per-leg ``outbound_url`` and
``return_url`` open each one-way separately, which is what the displayed price
is actually made of.
"""

from __future__ import annotations

from typing import Iterable

from flight_search.combine import FlightOption, Itinerary
from flight_search.config import SearchSettings

BOOKING_BASE = "https://www.google.com/travel/flights/booking"


def _seat_value(cabin: str) -> int:
    from fli.models import SeatType

    try:
        return SeatType[cabin.upper()].value
    except KeyError:
        return SeatType.ECONOMY.value


def _leg_specs(option: FlightOption) -> list:
    from fli.search._proto import LegSpec

    specs = []
    for leg in option.legs:
        if not (
            leg.airline
            and leg.flight_number
            and leg.origin
            and leg.destination
            and leg.departure
        ):
            raise ValueError(
                f"Incomplete leg data for {option.origin}->{option.destination}"
            )
        specs.append(
            LegSpec(
                origin=leg.origin,
                dep_date=leg.departure[:10],
                dest=leg.destination,
                airline=leg.airline,
                flight_number=leg.flight_number,
            )
        )
    if not specs:
        raise ValueError("Itinerary has no legs")
    return specs


def _build_token(
    segments: list[list], *, is_one_way: bool, settings: SearchSettings
) -> str:
    from fli.models import PassengerInfo
    from fli.search._proto import build_tfs_token, passenger_codes

    return build_tfs_token(
        segments,
        is_one_way=is_one_way,
        passengers=passenger_codes(PassengerInfo(adults=settings.adults)),
        seat=_seat_value(settings.cabin),
    )


def _booking_link(tfs: str, settings: SearchSettings) -> str:
    from fli.core.links import with_locale_params

    return with_locale_params(
        f"{BOOKING_BASE}?tfs={tfs}",
        settings.currency,
        settings.language,
        settings.country,
    )


def _search_link(option: FlightOption, settings: SearchSettings) -> str:
    """Route/date search fallback used only if token building ever breaks."""
    from fli.core.links import google_flights_url

    return google_flights_url(
        option.origin,
        option.destination,
        option.departure[:10],
        currency=settings.currency,
        language=settings.language,
        country=settings.country,
    )


def leg_url(option: FlightOption, settings: SearchSettings) -> str:
    """Deep link for one one-way leg."""
    try:
        tfs = _build_token([_leg_specs(option)], is_one_way=True, settings=settings)
        return _booking_link(tfs, settings)
    except Exception:  # noqa: BLE001 - a missing link must never break a run
        return _search_link(option, settings)


def itinerary_url(
    outbound: FlightOption, inbound: FlightOption, settings: SearchSettings
) -> str:
    """Deep link for the combined outbound + return itinerary."""
    try:
        tfs = _build_token(
            [_leg_specs(outbound), _leg_specs(inbound)],
            is_one_way=False,
            settings=settings,
        )
        return _booking_link(tfs, settings)
    except Exception:  # noqa: BLE001
        return _search_link(outbound, settings)


def attach_links(
    itineraries: Iterable[Itinerary], settings: SearchSettings
) -> None:
    """Populate the three Google Flights URLs on each itinerary."""
    for itinerary in itineraries:
        try:
            itinerary.booking_url = itinerary_url(
                itinerary.out, itinerary.ret, settings
            )
            itinerary.outbound_url = leg_url(itinerary.out, settings)
            itinerary.return_url = leg_url(itinerary.ret, settings)
        except Exception:  # noqa: BLE001
            # Leave links as None rather than failing a successful search.
            continue
