import pytest

from flight_search.airports import display_city, in_default_region, load_airports


@pytest.fixture(scope="module")
def by_iata():
    return {a.iata: a for a in load_airports(include_small=True)}


@pytest.mark.parametrize(
    ("iata", "expected"),
    [
        ("ATH", "Athens"),
        ("FUE", "Fuerteventura"),
        ("ACE", "Lanzarote"),
        ("SPC", "La Palma"),
        ("VDE", "El Hierro"),
        ("EFL", "Kefalonia"),
        ("KGS", "Kos"),
        ("ECN", "Ercan"),
    ],
)
def test_display_city_uses_common_name(by_iata, iata, expected):
    assert display_city(by_iata[iata]) == expected


def test_ercan_stays_in_default_region(by_iata):
    assert in_default_region(by_iata["ECN"])


@pytest.mark.parametrize(
    ("iata", "expected"),
    [
        ("GMZ", "La Gomera"),
        ("KZS", "Kastelorizo"),
    ],
)
def test_display_city_uses_common_name_for_small_island_airports(
    by_iata, iata, expected
):
    assert display_city(by_iata[iata]) == expected
