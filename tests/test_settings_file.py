"""The optional config file (PRTWO-CRITERION-11, -12, -13).

``$XDG_CONFIG_HOME/flight-search/config.toml`` (else ``~/.config/...``) sets
the defaults of the ``weekend`` and ``airports`` options, the home coordinate
and named regions. Every test drives ``cli.main``; the weekend search is
stopped at ``run_search``, whose ``SearchRequest`` shows what the run would
search. The conftest points ``XDG_CONFIG_HOME`` at an empty directory, and
each test writes its own file below it.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from airport_factory import airport

from flight_search import cli

MUC_LAT, MUC_LON = 48.354, 11.786

# AGB lies ~64 km from Munich, FKB ~25 km from Karlsruhe and ~270 km from
# Munich; TLV, BEY and AMM form the Levant, HFA is a small Israeli airport,
# LED (RU) and MSQ (BY) lie in the default region, SML is a small German one.
AIRPORTS = (
    airport("FRA", "DE", "EU", lat=50.03, lon=8.56),
    airport("FKB", "DE", "EU", lat=48.78, lon=8.08),
    airport("MUC", "DE", "EU", lat=MUC_LAT, lon=MUC_LON),
    airport("AGB", "DE", "EU", lat=48.425, lon=10.93),
    airport("SML", "DE", "EU", lat=49.2, lon=8.6, type="small_airport"),
    airport("LED", "RU", "EU", lat=59.80, lon=30.26),
    airport("MSQ", "BY", "EU", lat=53.88, lon=28.03),
    airport("TLV", "IL", "AS", lat=32.01, lon=34.89),
    airport("HFA", "IL", "AS", lat=32.81, lon=35.04, type="small_airport"),
    airport("BEY", "LB", "AS", lat=33.82, lon=35.49),
    airport("AMM", "JO", "AS", lat=31.72, lon=35.99),
)
ALL_MEDIUM = {a.iata for a in AIRPORTS if a.type != "small_airport"}

LEVANT = '[regions.levant]\ncountries = ["IL", "LB", "JO"]\n'


class FrozenDate(date):
    @classmethod
    def today(cls):
        return date(2027, 1, 15)


class _Stop(Exception):
    """Raised by the fake run_search once it has the request."""


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(cli, "load_airports", lambda include_small=False: AIRPORTS)
    monkeypatch.setattr(cli, "date", FrozenDate)
    # A wide, colourless console, so a long file path stays on one line.
    monkeypatch.setenv("COLUMNS", "1000")
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("TERM", "dumb")


def _config_file(config_home: Path) -> Path:
    return config_home / "flight-search" / "config.toml"


def _write_config(config_home: Path, text: str) -> Path:
    path = _config_file(config_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _run(argv: list[str]) -> int | str | None:
    try:
        return cli.main(argv)
    except SystemExit as exc:
        return exc.code


def _weekend_args(*extra: str) -> list[str]:
    return ["weekend", "--start", "2027-03-05", "--end", "2027-03-21", *extra]


def _weekend_request(monkeypatch, *extra: str):
    captured = {}

    def fake_run_search(request, **_kwargs):
        captured["request"] = request
        raise _Stop

    monkeypatch.setattr(cli, "run_search", fake_run_search)
    code = _run(_weekend_args(*extra))
    assert "request" in captured, f"the search was not reached (exit {code})"
    return captured["request"]


def _destination_codes(monkeypatch, *extra: str) -> set[str]:
    return {a.iata for a in _weekend_request(monkeypatch, *extra).destinations}


def _listed(capsys, *extra: str) -> dict[str, str]:
    """IATA code -> km column of the ``airports`` command."""
    capsys.readouterr()
    assert _run(["airports", *extra]) == 0
    out = capsys.readouterr().out
    codes = {a.iata for a in AIRPORTS}
    rows = {}
    for line in out.splitlines():
        words = line.split()
        if words and words[0] in codes:
            rows[words[0]] = words[-1]
    return rows


def _error(capsys, argv: list[str]) -> tuple[int | str | None, str]:
    capsys.readouterr()
    code = _run(argv)
    captured = capsys.readouterr()
    return code, (captured.err + captured.out).replace("\n", "")


# --- PRTWO-CRITERION-11: defaults from the file, the command line wins ---------


def test_without_a_config_file_the_weekend_search_is_unchanged(monkeypatch):
    request = _weekend_request(monkeypatch)
    assert tuple(request.home) == ("FKB", "STR", "SXB", "FRA")
    assert request.settings.currency == "EUR"


def test_config_home_airports_become_the_default_home(monkeypatch, xdg_config_home):
    _write_config(xdg_config_home, 'home_airports = ["MUC"]\n')
    assert tuple(_weekend_request(monkeypatch).home) == ("MUC",)


def test_config_home_airports_list_becomes_a_comma_separated_default(
    monkeypatch, xdg_config_home
):
    _write_config(xdg_config_home, 'home_airports = ["MUC", "FRA"]\n')
    assert tuple(_weekend_request(monkeypatch).home) == ("MUC", "FRA")


def test_from_on_the_command_line_overrides_the_config(monkeypatch, xdg_config_home):
    _write_config(xdg_config_home, 'home_airports = ["MUC"]\ncurrency = "USD"\n')
    request = _weekend_request(monkeypatch, "--from", "FRA")
    assert tuple(request.home) == ("FRA",)
    # The other values of the file still apply.
    assert request.settings.currency == "USD"


def test_config_currency_becomes_the_default(monkeypatch, xdg_config_home):
    _write_config(xdg_config_home, 'currency = "USD"\n')
    assert _weekend_request(monkeypatch).settings.currency == "USD"


def test_currency_on_the_command_line_overrides_the_config(
    monkeypatch, xdg_config_home
):
    _write_config(xdg_config_home, 'currency = "USD"\nhome_airports = ["MUC"]\n')
    request = _weekend_request(monkeypatch, "--currency", "CHF")
    assert request.settings.currency == "CHF"
    assert tuple(request.home) == ("MUC",)


def test_config_include_small_becomes_the_default(monkeypatch, xdg_config_home):
    _write_config(xdg_config_home, "include_small = true\n")
    assert "SML" in _destination_codes(monkeypatch, "--from", "FRA")


def test_config_exclude_countries_list_becomes_the_default(
    monkeypatch, xdg_config_home
):
    _write_config(xdg_config_home, 'exclude_countries = ["RU", "BY"]\n')
    codes = _destination_codes(monkeypatch, "--from", "FRA")
    assert "LED" not in codes
    assert "MSQ" not in codes
    assert {"FKB", "MUC", "AGB"} <= codes


def test_config_max_distance_km_becomes_the_default(monkeypatch, xdg_config_home):
    _write_config(xdg_config_home, "max_distance_km = 100\n")
    codes = _destination_codes(monkeypatch, "--from", "FRA", "--region", "weekend")
    assert codes == {"FKB"}


def test_config_region_becomes_the_default(monkeypatch, xdg_config_home):
    _write_config(xdg_config_home, 'region = "weekend"\nmax_distance_km = 100\n')
    assert _destination_codes(monkeypatch, "--from", "FRA") == {"FKB"}


def test_max_distance_km_on_the_command_line_overrides_the_config(
    monkeypatch, xdg_config_home
):
    _write_config(xdg_config_home, 'region = "weekend"\nmax_distance_km = 100\n')
    codes = _destination_codes(monkeypatch, "--from", "FRA", "--max-distance-km", "400")
    assert codes == {"FKB", "MUC", "AGB"}


def test_config_include_small_applies_to_the_airports_command(capsys, xdg_config_home):
    _write_config(xdg_config_home, "include_small = true\n")
    assert "SML" in _listed(capsys)


def test_a_weekend_only_key_is_ignored_by_the_airports_command(capsys, xdg_config_home):
    _write_config(
        xdg_config_home,
        'home_airports = ["MUC"]\ncurrency = "USD"\ninclude_small = true\n',
    )
    assert "SML" in _listed(capsys)


def test_an_unknown_key_ends_with_exit_2_naming_key_and_file(capsys, xdg_config_home):
    path = _write_config(xdg_config_home, 'colour = "blue"\n')
    code, message = _error(capsys, _weekend_args("--from", "FRA"))
    assert code == 2
    assert "colour" in message
    assert str(path) in message


def test_an_unknown_key_also_ends_the_airports_command(capsys, xdg_config_home):
    path = _write_config(xdg_config_home, 'colour = "blue"\n')
    code, message = _error(capsys, ["airports"])
    assert code == 2
    assert "colour" in message
    assert str(path) in message


@pytest.mark.parametrize(
    ("key", "line"),
    [
        ("include_small", 'include_small = "yes"'),
        ("max_distance_km", 'max_distance_km = "far"'),
    ],
)
def test_a_value_of_the_wrong_type_ends_with_exit_2_naming_the_key(
    capsys, xdg_config_home, key, line
):
    path = _write_config(xdg_config_home, line + "\n")
    code, message = _error(capsys, _weekend_args("--from", "FRA"))
    assert code == 2
    assert key in message
    assert str(path) in message


def test_without_xdg_config_home_the_file_is_read_from_dot_config(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    _write_config(tmp_path / ".config", 'home_airports = ["MUC"]\n')
    assert tuple(_weekend_request(monkeypatch).home) == ("MUC",)


# --- PRTWO-CRITERION-12: the home coordinate -----------------------------------

MUC_HOME = f"home = {{ lat = {MUC_LAT}, lon = {MUC_LON} }}\n"


def test_config_home_moves_the_weekend_radius_to_munich(monkeypatch, xdg_config_home):
    _write_config(xdg_config_home, MUC_HOME)
    codes = _destination_codes(
        monkeypatch, "--from", "FRA", "--region", "weekend", "--max-distance-km", "100"
    )
    assert codes == {"MUC", "AGB"}


def test_without_home_the_weekend_radius_stays_at_karlsruhe(
    monkeypatch, xdg_config_home
):
    _write_config(xdg_config_home, 'currency = "USD"\n')
    request = _weekend_request(
        monkeypatch, "--from", "FRA", "--region", "weekend", "--max-distance-km", "100"
    )
    assert request.settings.currency == "USD"
    assert {a.iata for a in request.destinations} == {"FKB"}


def test_config_home_moves_the_km_column_of_the_airports_command(
    capsys, xdg_config_home
):
    _write_config(xdg_config_home, MUC_HOME)
    rows = _listed(capsys, "--dest", "MUC,FKB")
    assert rows["MUC"] == "0"
    assert 250 < float(rows["FKB"]) < 300


def test_config_home_moves_the_airports_command_radius(capsys, xdg_config_home):
    _write_config(xdg_config_home, MUC_HOME)
    rows = _listed(capsys, "--region", "weekend", "--max-distance-km", "100")
    assert set(rows) == {"MUC", "AGB"}


@pytest.mark.parametrize(
    "line",
    [
        f"home = {{ lon = {MUC_LON} }}",
        f"home = {{ lat = {MUC_LAT} }}",
        f'home = {{ lat = "north", lon = {MUC_LON} }}',
    ],
)
def test_a_home_without_both_numbers_ends_with_exit_2_naming_home(
    capsys, xdg_config_home, line
):
    _write_config(xdg_config_home, line + "\n")
    code, message = _error(capsys, _weekend_args("--from", "FRA"))
    assert code == 2
    assert "home" in message


# --- PRTWO-CRITERION-13: named regions -----------------------------------------


def test_a_named_region_selects_its_countries_without_a_radius(
    monkeypatch, xdg_config_home
):
    _write_config(xdg_config_home, LEVANT)
    codes = _destination_codes(monkeypatch, "--from", "FRA", "--region", "levant")
    assert codes == {"TLV", "BEY", "AMM"}


def test_a_named_region_honours_include_small(monkeypatch, xdg_config_home):
    _write_config(xdg_config_home, LEVANT)
    codes = _destination_codes(
        monkeypatch, "--from", "FRA", "--region", "levant", "--include-small"
    )
    assert codes == {"TLV", "HFA", "BEY", "AMM"}


def test_a_named_region_honours_exclude(monkeypatch, xdg_config_home):
    _write_config(xdg_config_home, LEVANT)
    codes = _destination_codes(
        monkeypatch, "--from", "FRA", "--region", "levant", "--exclude", "TLV"
    )
    assert codes == {"BEY", "AMM"}


def test_a_named_region_honours_exclude_countries(monkeypatch, xdg_config_home):
    _write_config(xdg_config_home, LEVANT)
    codes = _destination_codes(
        monkeypatch, "--from", "FRA", "--region", "levant", "--exclude-countries", "IL"
    )
    assert codes == {"BEY", "AMM"}


def test_countries_override_a_named_region(monkeypatch, xdg_config_home):
    _write_config(xdg_config_home, LEVANT)
    codes = _destination_codes(
        monkeypatch, "--from", "FRA", "--region", "levant", "--countries", "JO"
    )
    assert codes == {"AMM"}


def test_dest_overrides_a_named_region(monkeypatch, xdg_config_home):
    _write_config(xdg_config_home, LEVANT)
    codes = _destination_codes(
        monkeypatch, "--from", "FRA", "--region", "levant", "--dest", "MUC"
    )
    assert codes == {"MUC"}


def test_the_airports_command_lists_a_named_region(capsys, xdg_config_home):
    _write_config(xdg_config_home, LEVANT)
    assert set(_listed(capsys, "--region", "levant")) == {"TLV", "BEY", "AMM"}


def test_the_airports_command_honours_exclude_countries_in_a_named_region(
    capsys, xdg_config_home
):
    _write_config(xdg_config_home, LEVANT)
    rows = _listed(capsys, "--region", "levant", "--exclude-countries", "LB")
    assert set(rows) == {"TLV", "AMM"}


@pytest.mark.parametrize("command", ["weekend", "airports"])
def test_help_lists_a_named_region_among_the_choices(capsys, xdg_config_home, command):
    _write_config(xdg_config_home, LEVANT)
    capsys.readouterr()
    assert _run([command, "--help"]) == 0
    assert "levant" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("europe", '[regions.europe]\ncountries = ["DE"]\n'),
        ("weekend", '[regions.weekend]\ncountries = ["DE"]\n'),
        ("nordics", "[regions.nordics]\n"),
    ],
)
def test_an_invalid_region_ends_with_exit_2_naming_the_region(
    capsys, xdg_config_home, name, text
):
    _write_config(xdg_config_home, text)
    code, message = _error(capsys, ["airports"])
    assert code == 2
    assert name in message


# --- PRTWO-CRITERION-17: unknown keys inside home and region tables ------------


def _error_or_crash(capsys, argv: list[str]) -> tuple[object, str]:
    """Like ``_error``, but an escaping exception becomes the code, not a crash."""
    capsys.readouterr()
    try:
        code = _run(argv)
    except Exception as exc:  # noqa: BLE001
        code = exc
    captured = capsys.readouterr()
    return code, (captured.err + captured.out).replace("\n", "")


def test_an_unknown_key_inside_home_ends_with_exit_2_naming_key_table_and_file(
    capsys, xdg_config_home
):
    path = _write_config(
        xdg_config_home, f"home = {{ lat = {MUC_LAT}, lon = {MUC_LON}, alt = 500 }}\n"
    )
    code, message = _error(capsys, ["airports"])
    assert code == 2
    assert "alt" in message
    assert "home" in message
    assert str(path) in message


def test_an_unknown_key_inside_a_region_ends_with_exit_2_naming_key_table_and_file(
    capsys, xdg_config_home
):
    path = _write_config(xdg_config_home, LEVANT + "radius = 500\n")
    code, message = _error(capsys, ["airports"])
    assert code == 2
    assert "radius" in message
    assert "levant" in message
    assert str(path) in message


@pytest.mark.parametrize(
    "line",
    [
        f"home = {{ lat = 91, lon = {MUC_LON} }}",
        f"home = {{ lat = -90.5, lon = {MUC_LON} }}",
        f"home = {{ lat = {MUC_LAT}, lon = 181 }}",
        f"home = {{ lat = {MUC_LAT}, lon = -180.5 }}",
        f"home = {{ lat = inf, lon = {MUC_LON} }}",
    ],
)
def test_a_home_outside_the_coordinate_range_ends_with_exit_2_naming_home(
    capsys, xdg_config_home, line
):
    path = _write_config(xdg_config_home, line + "\n")
    code, message = _error_or_crash(capsys, ["airports"])
    assert code == 2
    assert "home" in message
    assert str(path) in message


# --- PRTWO-CRITERION-18: the file is read safely, only for weekend and airports


@pytest.mark.parametrize("command", ["weekend", "airports"])
def test_a_config_file_that_is_not_utf8_ends_with_exit_2_naming_the_file(
    capsys, xdg_config_home, command
):
    path = _config_file(xdg_config_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'currency = "\xff\xfe"\n')
    argv = _weekend_args("--from", "FRA") if command == "weekend" else ["airports"]
    code, message = _error_or_crash(capsys, argv)
    assert code == 2
    assert str(path) in message
    assert "Traceback" not in message


@pytest.mark.parametrize("command", ["weekend", "airports"])
def test_a_config_file_that_cannot_be_read_ends_with_exit_2_naming_the_file(
    capsys, xdg_config_home, command
):
    path = _write_config(xdg_config_home, 'currency = "USD"\n')
    path.chmod(0)
    try:
        argv = _weekend_args("--from", "FRA") if command == "weekend" else ["airports"]
        code, message = _error_or_crash(capsys, argv)
    finally:
        path.chmod(0o644)
    assert code == 2
    assert str(path) in message
    assert "Traceback" not in message


BROKEN_CONFIGS = {
    "unknown key": b'colour = "blue"\n',
    "invalid toml": b"currency = \n",
    "not utf-8": b'currency = "\xff\xfe"\n',
}


@pytest.mark.parametrize("broken", sorted(BROKEN_CONFIGS))
@pytest.mark.parametrize(
    "argv",
    [["--version"], ["--help"], ["refresh-airports", "--help"]],
    ids=["version", "help", "refresh-airports-help"],
)
def test_version_and_help_work_with_a_broken_config_file(
    capsys, xdg_config_home, broken, argv
):
    path = _config_file(xdg_config_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(BROKEN_CONFIGS[broken])
    code, message = _error_or_crash(capsys, argv)
    assert code == 0, (code, message)


def _weekend_namespace(monkeypatch, *extra: str):
    captured = {}

    def fake_run_weekend(args):
        captured["args"] = args
        return 0

    monkeypatch.setattr(cli, "_run_weekend", fake_run_weekend)
    code = _run(_weekend_args(*extra))
    assert "args" in captured, f"the weekend command was not reached (exit {code})"
    return captured["args"]


@pytest.mark.parametrize(
    ("key", "attribute"), [("cache_dir", "cache_dir"), ("output", "output")]
)
def test_a_path_option_from_the_file_expands_the_home_directory(
    monkeypatch, xdg_config_home, tmp_path, key, attribute
):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    _write_config(xdg_config_home, f'{key} = "~/flight-search-files"\n')
    args = _weekend_namespace(monkeypatch, "--from", "FRA")
    assert Path(getattr(args, attribute)) == home / "flight-search-files"


# --- PRTWO-CRITERION-19: the command line wins over every value of the file ----

WEEKEND_FLAGS = (
    "include-small",
    "best-per-city",
    "compare-roundtrip",
    "dry-run",
    "verbose",
    "quiet",
    "cache",
)


@pytest.mark.parametrize("flag", WEEKEND_FLAGS)
def test_every_weekend_on_off_option_has_a_negative_form(flag):
    args = cli._build_parser().parse_args(_weekend_args(f"--{flag}", f"--no-{flag}"))
    assert getattr(args, flag.replace("-", "_")) is False


def test_the_airports_include_small_option_has_a_negative_form():
    args = cli._build_parser().parse_args(
        ["airports", "--include-small", "--no-include-small"]
    )
    assert args.include_small is False


def test_no_include_small_switches_off_include_small_from_the_file(
    monkeypatch, xdg_config_home
):
    _write_config(xdg_config_home, "include_small = true\n")
    codes = _destination_codes(monkeypatch, "--from", "FRA", "--no-include-small")
    assert "SML" not in codes
    assert "FKB" in codes


def test_no_dry_run_switches_off_dry_run_from_the_file(monkeypatch, xdg_config_home):
    _write_config(xdg_config_home, "dry_run = true\n")
    request = _weekend_request(monkeypatch, "--from", "FRA", "--no-dry-run")
    assert request.destinations


def test_airports_no_include_small_switches_off_include_small_from_the_file(
    capsys, xdg_config_home
):
    _write_config(xdg_config_home, "include_small = true\n")
    assert "SML" not in _listed(capsys, "--no-include-small")


def test_without_a_config_file_the_on_off_defaults_are_unchanged():
    args = cli._build_parser().parse_args(_weekend_args())
    for flag in WEEKEND_FLAGS:
        expected = flag == "cache"
        assert getattr(args, flag.replace("-", "_")) is expected, flag


@pytest.mark.parametrize(
    "line", ['countries = ["ES"]', 'dest = ["MUC"]'], ids=["countries", "dest"]
)
def test_region_on_the_command_line_wins_over_countries_or_dest_from_the_file(
    monkeypatch, xdg_config_home, line
):
    _write_config(xdg_config_home, line + "\n" + LEVANT)
    codes = _destination_codes(monkeypatch, "--from", "FRA", "--region", "levant")
    assert codes == {"TLV", "BEY", "AMM"}


def test_countries_on_the_command_line_still_win_over_region(
    monkeypatch, xdg_config_home
):
    _write_config(xdg_config_home, 'countries = ["ES"]\n' + LEVANT)
    codes = _destination_codes(
        monkeypatch, "--from", "FRA", "--region", "levant", "--countries", "JO"
    )
    assert codes == {"AMM"}


def test_dest_on_the_command_line_still_wins_over_region(monkeypatch, xdg_config_home):
    _write_config(xdg_config_home, 'countries = ["ES"]\n' + LEVANT)
    codes = _destination_codes(
        monkeypatch, "--from", "FRA", "--region", "levant", "--dest", "MUC"
    )
    assert codes == {"MUC"}


@pytest.mark.parametrize(
    ("key", "line"), [("start", 'start = "2027-03-05"'), ("end", 'end = "2027-03-21"')]
)
def test_a_required_option_in_the_file_is_an_unknown_key(
    capsys, xdg_config_home, key, line
):
    path = _write_config(xdg_config_home, line + "\n")
    code, message = _error(capsys, _weekend_args("--from", "FRA"))
    assert code == 2
    assert key in message
    assert str(path) in message
    assert "unknown" in message.lower()


def test_help_shows_the_default_from_the_file(capsys, xdg_config_home):
    _write_config(xdg_config_home, "max_candidates = 25\n")
    capsys.readouterr()
    assert _run(["weekend", "--help"]) == 0
    out = " ".join(capsys.readouterr().out.split())
    assert "(default: 25)" in out
    assert "(default: 60)" not in out


HELP_FILE_DEFAULTS = [
    ('currency = "CHF"\n', "weekend", "(default: CHF)"),
    ('countries = ["ES", "PT"]\n', "weekend", "(default: ES,PT)"),
    ('exclude_countries = ["RU"]\n', "weekend", "(default: RU)"),
    ('region = "weekend"\n', "weekend", "(default: weekend)"),
    ('region = "levant"\n' + LEVANT, "weekend", "(default: levant)"),
    ("include_small = true\n", "weekend", "(default: True)"),
    ("verbose = true\n", "weekend", "(default: True)"),
    ("dry_run = true\n", "weekend", "(default: True)"),
    ('countries = ["ES", "PT"]\n', "airports", "(default: ES,PT)"),
    ('exclude_countries = ["RU"]\n', "airports", "(default: RU)"),
    ("include_small = true\n", "airports", "(default: True)"),
    ('region = "weekend"\n', "airports", "(default: weekend)"),
    ('region = "levant"\n' + LEVANT, "airports", "(default: levant)"),
]


@pytest.mark.parametrize(("config", "command", "expected"), HELP_FILE_DEFAULTS)
def test_help_shows_every_file_default(
    capsys, xdg_config_home, config, command, expected
):
    _write_config(xdg_config_home, config)
    capsys.readouterr()
    assert _run([command, "--help"]) == 0
    out = " ".join(capsys.readouterr().out.split())
    assert expected in out


def test_help_shows_the_cache_dir_from_the_file(capsys, xdg_config_home):
    _write_config(xdg_config_home, 'cache_dir = "~/fs-cache"\n')
    capsys.readouterr()
    assert _run(["weekend", "--help"]) == 0
    out = " ".join(capsys.readouterr().out.split())
    assert f"(default: {Path('~/fs-cache').expanduser()})" in out
    assert "~/.cache/flight-search" not in out


def _help_option_line(help_text: str, option: str) -> str:
    return next(
        line for line in help_text.splitlines() if line.strip().startswith(option + " ")
    )


def test_help_shows_one_cache_line_defaulting_to_on_without_a_file(
    capsys, xdg_config_home
):
    capsys.readouterr()
    assert _run(["weekend", "--help"]) == 0
    out = capsys.readouterr().out
    line = _help_option_line(out, "--cache, --no-cache")
    assert "(default: True)" in line
    assert not any(ln.strip().startswith("--no-cache ") for ln in out.splitlines())


def test_help_shows_cache_default_off_with_cache_false_in_the_file(
    capsys, xdg_config_home
):
    _write_config(xdg_config_home, "cache = false\n")
    capsys.readouterr()
    assert _run(["weekend", "--help"]) == 0
    line = _help_option_line(capsys.readouterr().out, "--cache, --no-cache")
    assert "(default: False)" in line


def test_the_cache_is_on_by_default(monkeypatch, xdg_config_home):
    assert _weekend_namespace(monkeypatch, "--from", "FRA").cache is True


def test_cache_false_in_the_file_turns_the_cache_off(monkeypatch, xdg_config_home):
    _write_config(xdg_config_home, "cache = false\n")
    assert _weekend_namespace(monkeypatch, "--from", "FRA").cache is False


def test_cache_on_the_command_line_overrides_cache_false_in_the_file(
    monkeypatch, xdg_config_home
):
    _write_config(xdg_config_home, "cache = false\n")
    args = _weekend_namespace(monkeypatch, "--from", "FRA", "--cache")
    assert args.cache is True


def test_no_cache_on_the_command_line_turns_the_cache_off(monkeypatch, xdg_config_home):
    args = _weekend_namespace(monkeypatch, "--from", "FRA", "--no-cache")
    assert args.cache is False


def test_no_cache_is_no_longer_a_key_in_the_file(capsys, xdg_config_home):
    path = _write_config(xdg_config_home, "no_cache = true\n")
    code, message = _error(capsys, _weekend_args("--from", "FRA"))
    assert code == 2
    assert "no_cache" in message
    assert str(path) in message
    assert "unknown" in message.lower()


def test_help_without_a_file_keeps_the_builtin_defaults(capsys, xdg_config_home):
    capsys.readouterr()
    assert _run(["weekend", "--help"]) == 0
    out = " ".join(capsys.readouterr().out.split())
    assert "(default: ~/.cache/flight-search)" in out
    assert out.count("(default: True)") == 1  # only the cache switch
    assert out.count("(default: False)") >= 3


def test_airports_help_without_a_file_shows_off_for_include_small(
    capsys, xdg_config_home
):
    capsys.readouterr()
    assert _run(["airports", "--help"]) == 0
    out = " ".join(capsys.readouterr().out.split())
    assert "(default: False)" in out
    assert "(default: True)" not in out


# --- PRTWO-CRITERION-20: airports selects through select_destinations ----------


def test_airports_dest_overrides_a_named_region(capsys, xdg_config_home):
    _write_config(xdg_config_home, LEVANT)
    assert set(_listed(capsys, "--region", "levant", "--dest", "MUC")) == {"MUC"}


def test_airports_dest_overrides_a_named_region_from_the_file(
    monkeypatch, capsys, xdg_config_home
):
    naxos = airport("JNX", "GR", "EU", lat=37.08, lon=25.37)
    monkeypatch.setattr(
        cli, "load_airports", lambda include_small=False: (*AIRPORTS, naxos)
    )
    _write_config(xdg_config_home, 'region = "levant"\n' + LEVANT)
    capsys.readouterr()
    assert _run(["airports", "--dest", "JNX"]) == 0
    out = capsys.readouterr().out
    assert "JNX" in out.split()
    assert not {"TLV", "BEY", "AMM"} & set(out.split())


def test_airports_builds_a_destination_choice_for_select_destinations(
    monkeypatch, capsys
):
    from flight_search.destinations import DestinationChoice

    calls = []
    real = cli.select_destinations

    def spy(choice, **kwargs):
        calls.append(choice)
        return real(choice, **kwargs)

    monkeypatch.setattr(cli, "select_destinations", spy)
    _listed(capsys, "--dest", "MUC")
    assert len(calls) == 1
    assert isinstance(calls[0], DestinationChoice)
    assert calls[0].codes == ("MUC",)
