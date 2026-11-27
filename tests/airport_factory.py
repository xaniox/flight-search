"""One factory for synthetic airports in tests."""

from flight_search.airports import AirportInfo


def airport(
    iata: str,
    country: str = "DE",
    continent: str = "EU",
    *,
    municipality: str | None = None,
    lat: float = 49.0,
    lon: float = 8.5,
    type: str = "medium_airport",
) -> AirportInfo:
    return AirportInfo(
        iata=iata,
        name=f"{iata} Airport",
        municipality=municipality if municipality is not None else iata,
        country=country,
        type=type,
        continent=continent,
        lat=lat,
        lon=lon,
    )
