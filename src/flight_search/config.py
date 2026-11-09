"""Static configuration for the flight search tool."""

from __future__ import annotations

from dataclasses import dataclass, field

# Karlsruhe (city centre) — used for the "weekend" distance preset.
KARLSRUHE_LAT = 49.013
KARLSRUHE_LON = 8.404

DEFAULT_HOME_AIRPORTS = ("FKB", "STR", "SXB", "FRA")

# OurAirports "continent" covers Europe (including the European part of Russia).
# North Africa, Turkey and the Caucasus are added explicitly by ISO country code.
NORTH_AFRICA_COUNTRIES = frozenset({"MA", "DZ", "TN", "LY", "EG", "EH"})
TURKEY_CAUCASUS_COUNTRIES = frozenset({"TR", "GE", "AZ", "AM"})
INCLUDED_COUNTRIES = NORTH_AFRICA_COUNTRIES | TURKEY_CAUCASUS_COUNTRIES

MEDIUM_LARGE = frozenset({"large_airport", "medium_airport"})

DEFAULT_CURRENCY = "EUR"
DEFAULT_COUNTRY = "DE"
DEFAULT_LANGUAGE = "de-DE"

WEEKDAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass(frozen=True, slots=True)
class SearchSettings:
    """Everything that changes the Google Flights request itself."""

    cabin: str = "ECONOMY"
    max_stops: str = "ANY"
    adults: int = 1
    currency: str = DEFAULT_CURRENCY
    country: str | None = DEFAULT_COUNTRY
    language: str | None = DEFAULT_LANGUAGE

    def cache_key(self) -> dict[str, object]:
        return {
            "cabin": self.cabin,
            "max_stops": self.max_stops,
            "adults": self.adults,
            "currency": self.currency,
            "country": self.country,
            "language": self.language,
        }


@dataclass(slots=True)
class RunPlan:
    """Resolved, human-readable description of what a run will do."""

    home_airports: tuple[str, ...] = DEFAULT_HOME_AIRPORTS
    destination_airports: tuple[str, ...] = ()
    trips: int = 0
    screen_requests: int = 0
    detail_requests: int = 0
    notes: list[str] = field(default_factory=list)
