"""Flight option normalisation, open-jaw combination and ranking."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable

from flight_search.windows import DepartureWindow, ReturnArrivalWindow


@dataclass(frozen=True, slots=True)
class LegInfo:
    airline: str
    airline_name: str
    flight_number: str
    origin: str
    destination: str
    departure: str
    arrival: str
    duration: int
    aircraft: str | None = None
    overnight: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "airline": self.airline,
            "airline_name": self.airline_name,
            "flight_number": self.flight_number,
            "origin": self.origin,
            "destination": self.destination,
            "departure": self.departure,
            "arrival": self.arrival,
            "duration": self.duration,
            "aircraft": self.aircraft,
            "overnight": self.overnight,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LegInfo":
        return cls(**data)


@dataclass(frozen=True, slots=True)
class FlightOption:
    """One bookable one-way itinerary."""

    price: float
    currency: str
    departure: str
    arrival: str
    stops: int
    duration: int
    legs: tuple[LegInfo, ...] = field(default_factory=tuple)

    @property
    def origin(self) -> str:
        return self.legs[0].origin if self.legs else ""

    @property
    def destination(self) -> str:
        return self.legs[-1].destination if self.legs else ""

    @property
    def signature(self) -> tuple[str, ...]:
        return tuple(
            f"{leg.airline}{leg.flight_number}@{leg.departure}" for leg in self.legs
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "price": self.price,
            "currency": self.currency,
            "departure": self.departure,
            "arrival": self.arrival,
            "stops": self.stops,
            "duration": self.duration,
            "legs": [leg.to_dict() for leg in self.legs],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FlightOption":
        return cls(
            price=float(data["price"]),
            currency=data["currency"],
            departure=data["departure"],
            arrival=data["arrival"],
            stops=int(data["stops"]),
            duration=int(data["duration"]),
            legs=tuple(LegInfo.from_dict(leg) for leg in data.get("legs", [])),
        )


def _clean_code(value: str) -> str:
    return value.removeprefix("_")


def _option_from_result(result: Any) -> FlightOption | None:
    if result is None or isinstance(result, tuple):
        return None
    if getattr(result, "price", None) is None:
        return None
    legs = getattr(result, "legs", None) or []
    if not legs:
        return None
    leg_infos: list[LegInfo] = []
    for leg in legs:
        leg_infos.append(
            LegInfo(
                airline=_clean_code(leg.airline.name),
                airline_name=leg.airline.value,
                flight_number=str(leg.flight_number),
                origin=leg.departure_airport.name,
                destination=leg.arrival_airport.name,
                departure=leg.departure_datetime.isoformat(),
                arrival=leg.arrival_datetime.isoformat(),
                duration=int(leg.duration),
                aircraft=getattr(leg, "aircraft", None),
                overnight=bool(getattr(leg, "overnight", False)),
            )
        )
    return FlightOption(
        price=float(result.price),
        currency=result.currency or "EUR",
        departure=leg_infos[0].departure,
        arrival=leg_infos[-1].arrival,
        stops=int(result.stops),
        duration=int(result.duration),
        legs=tuple(leg_infos),
    )


def options_from_results(results: Iterable[Any]) -> list[FlightOption]:
    options: list[FlightOption] = []
    for result in results:
        option = _option_from_result(result)
        if option is not None:
            options.append(option)
    return options


def filter_departures(
    options: Iterable[FlightOption], window: DepartureWindow
) -> list[FlightOption]:
    if not window.active:
        return list(options)
    return [
        option
        for option in options
        if window.matches(datetime.fromisoformat(option.departure))
    ]


def filter_return_arrivals(
    options: Iterable[FlightOption],
    window: ReturnArrivalWindow,
    return_date: date,
) -> list[FlightOption]:
    if not window.active:
        return list(options)
    return [
        option
        for option in options
        if window.matches(datetime.fromisoformat(option.arrival), return_date)
    ]


def reduce_best(options: Iterable[FlightOption]) -> dict[tuple[str, str], FlightOption]:
    """Cheapest option per (origin, destination) airport pair.

    The two legs are separate tickets, so for a given airport pairing the
    optimal total is always the cheapest outbound plus the cheapest return.
    """
    best: dict[tuple[str, str], FlightOption] = {}
    for option in options:
        key = (option.origin, option.destination)
        current = best.get(key)
        if current is None or _rank(option) < _rank(current):
            best[key] = option
    return best


def _rank(option: FlightOption) -> tuple[float, int, int, str]:
    return (option.price, option.stops, option.duration, option.departure)


@dataclass(slots=True)
class Itinerary:
    city_key: str
    city: str
    country: str
    city_codes: tuple[str, ...]
    depart_date: date
    return_date: date
    out: FlightOption
    ret: FlightOption
    roundtrip_price: float | None = None
    booking_url: str | None = None
    outbound_url: str | None = None
    return_url: str | None = None

    @property
    def total(self) -> float:
        return self.out.price + self.ret.price

    @property
    def nights(self) -> int:
        return (self.return_date - self.depart_date).days

    @property
    def open_jaw_home(self) -> bool:
        return self.out.origin != self.ret.destination

    @property
    def open_jaw_destination(self) -> bool:
        return self.out.destination != self.ret.origin

    @property
    def open_jaw_label(self) -> str:
        if self.open_jaw_home and self.open_jaw_destination:
            return "both"
        if self.open_jaw_home:
            return "home"
        if self.open_jaw_destination:
            return "dest"
        return ""

    @property
    def roundtrip_delta(self) -> float | None:
        if self.roundtrip_price is None:
            return None
        return self.total - self.roundtrip_price

    def to_dict(self) -> dict[str, Any]:
        return {
            "city": self.city,
            "country": self.country,
            "depart_date": self.depart_date.isoformat(),
            "return_date": self.return_date.isoformat(),
            "nights": self.nights,
            "total": round(self.total, 2),
            "currency": self.out.currency,
            "open_jaw": {
                "home": self.open_jaw_home,
                "destination": self.open_jaw_destination,
                "label": self.open_jaw_label,
            },
            "outbound": self.out.to_dict(),
            "return": self.ret.to_dict(),
            "roundtrip_price": self.roundtrip_price,
            "roundtrip_delta": self.roundtrip_delta,
            "booking_url": self.booking_url,
            "outbound_url": self.outbound_url,
            "return_url": self.return_url,
        }


def combine_itineraries(
    *,
    city_key: str,
    city: str,
    country: str,
    city_codes: tuple[str, ...],
    depart_date: date,
    return_date: date,
    outbound_options: Iterable[FlightOption],
    return_options: Iterable[FlightOption],
) -> list[Itinerary]:
    out_best = reduce_best(outbound_options)
    ret_best = reduce_best(return_options)
    if not out_best or not ret_best:
        return []

    itineraries: list[Itinerary] = []
    seen: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
    for outbound in out_best.values():
        for inbound in ret_best.values():
            signature = (outbound.signature, inbound.signature)
            if signature in seen:
                continue
            seen.add(signature)
            itineraries.append(
                Itinerary(
                    city_key=city_key,
                    city=city,
                    country=country,
                    city_codes=city_codes,
                    depart_date=depart_date,
                    return_date=return_date,
                    out=outbound,
                    ret=inbound,
                )
            )
    itineraries.sort(key=lambda item: (item.total, item.depart_date, item.return_date))
    return itineraries
