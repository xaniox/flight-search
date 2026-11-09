"""Regenerate the vendored airport snapshot from OurAirports."""

from __future__ import annotations

import csv
import io
import urllib.request
from pathlib import Path

from fli.models.airport import AIRPORT_NAMES

from flight_search.config import MEDIUM_LARGE, NORTH_AFRICA_COUNTRIES

OURAIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"

FIELDS = (
    "iata",
    "name",
    "municipality",
    "iso_country",
    "type",
    "continent",
    "latitude_deg",
    "longitude_deg",
)


def dataset_path() -> Path:
    return Path(__file__).parent / "data" / "airports_eu_na.csv"


def fetch_ourairports(url: str = OURAIRPORTS_URL, timeout: int = 90) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "flight-search/0.1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.read().decode("utf-8")


def build_rows(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    reader = csv.DictReader(io.StringIO(text))
    for record in reader:
        if record.get("scheduled_service") != "yes":
            continue
        if record.get("type") not in {"large_airport", "medium_airport", "small_airport"}:
            continue
        code = (record.get("iata_code") or "").strip().upper()
        if not code or code in seen:
            continue
        if record.get("continent") != "EU" and record.get("iso_country") not in NORTH_AFRICA_COUNTRIES:
            continue
        if code not in AIRPORT_NAMES:
            # fli cannot query airports missing from its enum.
            continue
        seen.add(code)
        rows.append(
            {
                "iata": code,
                "name": record.get("name", ""),
                "municipality": record.get("municipality", ""),
                "iso_country": (record.get("iso_country") or "").upper(),
                "type": record.get("type", ""),
                "continent": record.get("continent", ""),
                "latitude_deg": record.get("latitude_deg", ""),
                "longitude_deg": record.get("longitude_deg", ""),
            }
        )
    rows.sort(key=lambda row: row["iata"])
    return rows


def write_rows(rows: list[dict[str, str]], path: Path | None = None) -> Path:
    target = path or dataset_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return target


def refresh_airports(path: Path | None = None, url: str = OURAIRPORTS_URL) -> dict[str, int]:
    rows = build_rows(fetch_ourairports(url))
    write_rows(rows, path)
    return {
        "total": len(rows),
        "medium_large": sum(1 for row in rows if row["type"] in MEDIUM_LARGE),
        "small": sum(1 for row in rows if row["type"] == "small_airport"),
    }
