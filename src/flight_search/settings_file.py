"""The optional config file: option defaults, the home coordinate and named regions.

``$XDG_CONFIG_HOME/flight-search/config.toml`` (else ``~/.config/...``). Its
top-level keys are the destination names of the subcommand options; a value
becomes the option's default, so a flag on the command line still wins.
"""

from __future__ import annotations

import argparse
import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from flight_search.config import Coordinate

BUILT_IN_REGIONS = ("europe", "weekend")


class ConfigError(ValueError):
    """The config file cannot be used; the message names the file."""


@dataclass(frozen=True, slots=True)
class Settings:
    path: Path | None = None
    options: Mapping[str, object] = field(default_factory=dict)
    home: Coordinate | None = None
    regions: Mapping[str, frozenset[str]] = field(default_factory=dict)


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base) if base else Path.home() / ".config"
    return root / "flight-search" / "config.toml"


def load(path: Path | None = None) -> Settings:
    """The settings of the file; empty settings when there is no file."""
    path = path or config_path()
    if not path.is_file():
        return Settings()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    home = _home(data.pop("home", None), path)
    regions = _regions(data.pop("regions", {}), path)
    return Settings(path=path, options=data, home=home, regions=regions)


def apply_defaults(settings: Settings, parsers: Mapping[str, argparse.ArgumentParser]):
    """Set the file's option values as defaults of each parser that has the option.

    A key no parser has, a key of a required option, or a value of the wrong
    type raises ``ConfigError``.
    """
    actions = {
        name: {
            a.dest: a
            for a in parser._actions
            if a.default is not argparse.SUPPRESS and not a.required
        }
        for name, parser in parsers.items()
    }
    defaults: dict[str, dict[str, object]] = {name: {} for name in parsers}
    for key, value in settings.options.items():
        owners = [name for name in parsers if key in actions[name]]
        if not owners:
            raise ConfigError(f"{settings.path}: unknown key {key!r}")
        for name in owners:
            defaults[name][key] = _value(key, actions[name][key], value, settings.path)
    for name, parser in parsers.items():
        parser.set_defaults(**defaults[name])


def _value(key: str, action: argparse.Action, value: object, path: Path | None):
    if action.nargs == 0:  # on/off options
        if isinstance(value, bool):
            return value
        raise ConfigError(f"{path}: {key!r} must be true or false")
    if action.type in (int, float):
        allowed = (int, float) if action.type is float else int
        if isinstance(value, allowed) and not isinstance(value, bool):
            return action.type(value)
        raise ConfigError(f"{path}: {key!r} must be a number")
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        value = ",".join(value)
    if not isinstance(value, str):
        raise ConfigError(f"{path}: {key!r} must be a string or a list of strings")
    if action.type is Path:
        return Path(value).expanduser()
    if action.choices is not None and value not in action.choices:
        raise ConfigError(
            f"{path}: {key!r} must be one of {', '.join(map(str, action.choices))}"
        )
    return value


def _no_unknown_keys(table: dict, allowed: set[str], name: str, path: Path) -> None:
    for key in table:
        if key not in allowed:
            raise ConfigError(f"{path}: unknown key {key!r} in {name}")


def _home(value: object, path: Path) -> Coordinate | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ConfigError(f"{path}: 'home' needs the numbers lat and lon")
    _no_unknown_keys(value, {"lat", "lon"}, "'home'", path)
    lat, lon = value.get("lat"), value.get("lon")
    if not all(
        isinstance(n, int | float) and not isinstance(n, bool) for n in (lat, lon)
    ):
        raise ConfigError(f"{path}: 'home' needs the numbers lat and lon")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):  # NaN and inf fail too
        raise ConfigError(
            f"{path}: 'home' needs lat within -90..90 and lon within -180..180"
        )
    return Coordinate(float(lat), float(lon))


def _regions(value: object, path: Path) -> dict[str, frozenset[str]]:
    if not isinstance(value, dict):
        raise ConfigError(f"{path}: 'regions' must be a table of [regions.<name>]")
    regions = {}
    for name, region in value.items():
        if name in BUILT_IN_REGIONS:
            raise ConfigError(f"{path}: region {name!r} is built in")
        if isinstance(region, dict):
            _no_unknown_keys(region, {"countries"}, f"[regions.{name}]", path)
        countries = region.get("countries") if isinstance(region, dict) else None
        if not (
            isinstance(countries, list)
            and countries
            and all(isinstance(code, str) for code in countries)
        ):
            raise ConfigError(f"{path}: region {name!r} needs a list of countries")
        regions[name] = frozenset(code.strip().upper() for code in countries)
    return regions
