"""Airport metadata, city grouping and region filtering.

The vendored CSV is generated from OurAirports by ``scripts/refresh_airports.py``
and restricted to scheduled-service airports in Europe / North Africa that also
exist in ``fli``'s ``Airport`` enum.
"""

from __future__ import annotations

import csv
import math
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources

from flight_search.config import KARLSRUHE_LAT, KARLSRUHE_LON, MEDIUM_LARGE

DATA_PACKAGE = "flight_search.data"
AIRPORTS_FILE = "airports_eu_na.csv"
METROS_FILE = "metros.toml"


@dataclass(frozen=True, slots=True)
class AirportInfo:
    iata: str
    name: str
    municipality: str
    country: str
    type: str
    continent: str
    lat: float
    lon: float

    @property
    def city(self) -> str:
        return self.municipality.strip() or self.name.strip()

    @property
    def is_small(self) -> bool:
        return self.type == "small_airport"


@dataclass(frozen=True, slots=True)
class CityGroup:
    """One destination "place" — one or more airports that may be mixed."""

    key: str
    display: str
    country: str
    airports: tuple[AirportInfo, ...]

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(a.iata for a in self.airports)

    @property
    def distance_km(self) -> float:
        if not self.airports:
            return float("inf")
        return min(distance_from_karlsruhe(a) for a in self.airports)


class AirportDataError(RuntimeError):
    """Raised when the vendored airport data is missing or malformed."""


def _open_data(name: str):
    try:
        return resources.files(DATA_PACKAGE).joinpath(name).open("rb")
    except (FileNotFoundError, ModuleNotFoundError) as exc:  # pragma: no cover
        raise AirportDataError(
            f"Missing airport data file {name!r}. Run `flight-search refresh-airports`."
        ) from exc


@lru_cache(maxsize=4)
def load_airports(include_small: bool = False) -> tuple[AirportInfo, ...]:
    """Load the vendored airport snapshot."""
    allowed_types = MEDIUM_LARGE | ({"small_airport"} if include_small else set())
    rows: list[AirportInfo] = []
    with _open_data(AIRPORTS_FILE) as fh:
        reader = csv.DictReader(fh.read().decode("utf-8").splitlines())
        for row in reader:
            if row["type"] not in allowed_types:
                continue
            try:
                lat = float(row["latitude_deg"])
                lon = float(row["longitude_deg"])
            except (KeyError, TypeError, ValueError):
                continue
            rows.append(
                AirportInfo(
                    iata=row["iata"].upper(),
                    name=row["name"],
                    municipality=row.get("municipality", ""),
                    country=row["iso_country"].upper(),
                    type=row["type"],
                    continent=row["continent"],
                    lat=lat,
                    lon=lon,
                )
            )
    rows.sort(key=lambda a: a.iata)
    return tuple(rows)


@lru_cache(maxsize=1)
def metro_map() -> dict[str, str]:
    """Map IATA code -> metro display name for airports that share a metro area."""
    data = tomllib.loads(_open_data(METROS_FILE).read().decode("utf-8"))
    mapping: dict[str, str] = {}
    for name, cfg in data.get("metros", {}).items():
        display = cfg.get("display", name.replace("_", " ").title())
        for code in cfg.get("airports", []):
            mapping[code.upper()] = display
    return mapping


@lru_cache(maxsize=1)
def name_map() -> dict[str, str]:
    """Map IATA code -> preferred city display name."""
    data = tomllib.loads(_open_data(METROS_FILE).read().decode("utf-8"))
    return {code.upper(): name for code, name in data.get("names", {}).items()}


def build_city_groups(
    airports: tuple[AirportInfo, ...] | list[AirportInfo],
) -> list[CityGroup]:
    """Group airports into destinations, honouring the curated metro map."""
    met = metro_map()
    names = name_map()
    buckets: dict[str, list[AirportInfo]] = {}
    displays: dict[str, str] = {}
    countries: dict[str, str] = {}

    for airport in airports:
        metro = met.get(airport.iata)
        if metro:
            key = f"metro:{metro.lower()}"
            display = metro
        else:
            city = names.get(airport.iata) or airport.city
            key = f"city:{airport.country}:{city.lower()}"
            display = city
        buckets.setdefault(key, []).append(airport)
        displays.setdefault(key, display)
        countries.setdefault(key, airport.country)

    groups = [
        CityGroup(
            key=key,
            display=displays[key],
            country=countries[key],
            airports=tuple(sorted(items, key=lambda a: a.iata)),
        )
        for key, items in buckets.items()
    ]
    groups.sort(key=lambda g: (g.country, g.display.lower()))
    return groups


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def distance_from_karlsruhe(airport: AirportInfo) -> float:
    return haversine_km(KARLSRUHE_LAT, KARLSRUHE_LON, airport.lat, airport.lon)


def filter_airports(
    airports: tuple[AirportInfo, ...],
    *,
    codes: tuple[str, ...] = (),
    countries: frozenset[str] = frozenset(),
    max_distance_km: float | None = None,
    exclude: frozenset[str] = frozenset(),
) -> tuple[AirportInfo, ...]:
    """Apply explicit code / country / distance filters."""
    selected = airports
    if codes:
        wanted = {c.upper() for c in codes}
        selected = tuple(a for a in selected if a.iata in wanted)
    if countries:
        selected = tuple(a for a in selected if a.country in countries)
    if max_distance_km is not None:
        selected = tuple(
            a for a in selected if distance_from_karlsruhe(a) <= max_distance_km
        )
    if exclude:
        selected = tuple(a for a in selected if a.iata not in exclude)
    return selected


def airport_lookup(
    airports: tuple[AirportInfo, ...],
) -> dict[str, AirportInfo]:
    return {a.iata: a for a in airports}
