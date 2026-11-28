# flight-search

Weekend-getaway and open-jaw flight search on top of
[`fli`](https://github.com/punitarani/fli) (Google Flights), from the
Karlsruhe area by default.

Given a date range, a set of departure weekdays, a set of return weekdays and
an airport region, it prices every matching weekend and returns the cheapest
**two separate one-way tickets**, including open-jaw combinations such as
outbound `FRA → FCO` and return `CIA → FRA`.

```text
#  Total  City        Flights                                    Nights  Seg  Open jaw  Link
1   €101  Rome (IT)   out  Fri 19 Mar  FRA→FCO  FR  18:40–20:28       2    2    dest    open
                      ret  Sun 21 Mar  CIA→FRA  VY  20:05–21:42
2   €104  Rome (IT)   out  Fri 05 Mar  FRA→CIA  VY  18:40–20:17       2    2     —      open
                      ret  Sun 07 Mar  CIA→FRA  VY  20:05–21:42
```

`Flights` shows the outbound and return separately. `Seg` counts the flight
segments in both directions combined. A route such as `MUC→LGW ⇢ STN→ATH`
uses `⇢` for the transfer between airports. `--best-per-city` uses the same
route format.

`open` is a clickable Google Flights deep link for that exact itinerary. In
terminals without OSC-8 hyperlink support (or when the output is piped), the
full URLs are printed below the table; `--format json` always contains them.

## Install

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```sh
uv sync
uv run flight-search --help
```

For a global command (this is what is installed on this machine):

```sh
uv tool install --editable .
# then, with ~/.local/bin on PATH:
flight-search --help
```

The examples below use `uv run flight-search`; a globally installed
`flight-search` works identically.

### Windows

Requires Python 3.12+ and uv:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
uv sync
uv run flight-search --help
```

`uv tool install --editable .` adds a global `flight-search` command (run
`uv tool update-shell`, then restart the shell). The cache is
`%USERPROFILE%\.cache\flight-search`; Windows Terminal renders clickable
links, and `--output results.json` avoids PowerShell 5.1's UTF-16 `>`
redirection.

## Quick start

Cheapest weekend across Europe including Cyprus, the Greek islands and the
Canaries, plus North Africa, Turkey and the Caucasus, over the next two weeks: (658 airports — roughly 2–4 minutes on a cold cache)

```sh
uv run flight-search weekend \
  --start 2026-11-13 --end 2026-11-30 \
  --depart-days fri --return-days sun,mon \
  --min-nights 2 --max-nights 3 \
  --top 20 --best-per-city
```

A faster short-haul scan (airports within 1200 km of Karlsruhe, ~1–2 minutes):

```sh
uv run flight-search weekend \
  --region weekend \
  --start 2026-11-13 --end 2026-11-30 \
  --depart-days thu,fri --return-days sun,mon
```

A specific city group:

```sh
uv run flight-search weekend \
  --dest BCN,GRO,REU \
  --start 2026-11-13 --end 2026-11-30 \
  --depart-days fri --return-days sun
```

Only Spain, with a departure window and a Sunday-evening deadline, plus a
round-trip price comparison:

```sh
uv run flight-search weekend \
  --countries ES,PT \
  --start 2026-11-13 --end 2026-12-14 \
  --depart-days fri --return-days sun \
  --depart-after 17:30 --depart-before 21:15 \
  --return-depart-after 15:00 --return-arrive-before 22:00 \
  --compare-roundtrip --top 15
```

Machine-readable output:

```sh
uv run flight-search weekend ... --format json > results.json
```

## Options worth knowing

| Option | Meaning |
| --- | --- |
| `--from` | Home airports, default `FKB,STR,SXB,FRA`. All are searched at once. |
| `--region europe\|weekend\|<name>` | `europe` = every scheduled airport in Europe including Cyprus, the Greek islands and the Canaries, plus North Africa, Turkey and the Caucasus (658); `weekend` = the same, within `--max-distance-km` of Karlsruhe (or the `home` of the config file); `<name>` = a named region from the config file. |
| `--countries`, `--dest`, `--exclude`, `--include-small` | Override or narrow the destination set. `--countries` and `--dest` choose from the worldwide dataset, e.g. `--countries IL` or `--dest TLV`. `--include-small` adds small scheduled airports (more requests); airports named by `--dest` or `--from` are always used, even when small. |
| `--exclude-countries` | Leave out whole countries, e.g. `RU,BY`; explicit `--dest` codes are kept. |
| `--depart-days`, `--return-days` | Weekday sets, e.g. `thu,fri` and `sun,mon`. |
| `--start`, `--end` | Date range; both legs must fall inside it. |
| `--min-nights`, `--max-nights` | Trip length constraint. |
| `--depart-after`, `--depart-before` | Optional outbound departure window, local time (`17:30`, `21:15`). |
| `--return-depart-after` | Optional earliest return departure from the destination, local time (`15:00`). |
| `--return-arrive-before` | Optional latest return arrival at the home airport, local time. |
| `--airlines`, `--allow-codeshare` | Keep only itineraries where the selling and the operating airline of every leg are listed, e.g. `--airlines A3,OA`; `--allow-codeshare` checks the selling airline only, and a leg without a reported operator counts as operated by its seller. The price is the cheapest matching flight Google returned in a batch, so cheaper matching flights or whole destinations can be missing. |
| `--max-stops` | `ANY`, `0`/`NON_STOP`, `1`/`ONE_STOP`, `2+`. |
| `--top`, `--best-per-city`, `--per-city` | Display count and city diversity in the confirmed shortlist. |
| `--compare-roundtrip` | Also price a conventional same-airport round-trip across all airlines, even with `--airlines`. |
| `--max-candidates` | How many city/date-pair candidates are confirmed exactly (default 60). |
| `--cache-ttl`, `--cache`/`--no-cache` | Disk cache lifetime (default 12h) in `~/.cache/flight-search`; `--no-cache` bypasses it, `--cache` undoes `cache = false` from the config file. |
| `--concurrency`, `--max-requests` | Parallelism and a hard request ceiling. |
| `--dry-run` | Print the plan and request estimate without network calls. |

Every on/off option has a negative form that switches it off again, for
example when the config file switches it on: `--no-include-small`,
`--no-allow-codeshare`, `--no-best-per-city`, `--no-compare-roundtrip`,
`--no-dry-run`, `--no-verbose` and `--no-quiet`. `airports --help` and
`weekend --help` show the defaults in effect, including those from the config file.

Time windows are optional; when omitted the whole day qualifies. That covers
the outbound departure window (`--depart-after`/`--depart-before`), the return
departure floor (`--return-depart-after`) and the return arrival deadline
(`--return-arrive-before`).

Google's request format only understands whole hours and its bounds are
inclusive of the whole hour, and the arrival bound is not date-aware. The tool
therefore sends permissive hour bounds and enforces the exact minute (and the
same-day rule, so a Monday 01:00 red-eye does not pass a Sunday 22:00 deadline)
locally on the decoded itineraries. `--return-depart-after 15` and
`--return-arrive-before 22:30` are both valid forms.

## Configuration

An optional file `~/.config/flight-search/config.toml` (or
`$XDG_CONFIG_HOME/flight-search/config.toml`) sets your own defaults for
`weekend` and `airports`:

```toml
home_airports = ["MUC"]          # like --from MUC
currency = "EUR"
exclude_countries = ["RU", "BY"]
airlines = ["A3", "OA"]          # like --airlines A3,OA
allow_codeshare = true           # like --allow-codeshare
home = { lat = 48.354, lon = 11.786 }  # measure --region weekend and the km column from here

[regions.levant]
countries = ["IL", "LB", "JO"]
```

The keys are the option names with `_` instead of `-` (`--from` is
`home_airports`); lists become comma-separated values, and `~` in `cache_dir`
and `output` means your home directory. The command line wins over the file,
the file over the built-in default. `--dest` and `--countries` override
`--region europe` and a named region; with `--region weekend` the radius
still applies to `--countries`, not to `--dest`. Once the
command line names any of `--region`, `--countries` or `--dest`, the file's `countries` and `dest` no longer apply, so
`countries = ["ES"]` in the file plus `--region levant` searches the Levant.
A named region is used as `--region levant`: it selects the airports of its
countries worldwide, like `--countries IL,LB,JO`, and has no radius;
`--countries` and `--dest` override it. Without `home` distances are measured
from Karlsruhe. The file is read only by `weekend` and `airports`. An unknown
key (also inside `home` or a region, and `start`/`end`, which belong on the
command line), a value of the wrong type, a `home` outside -90..90 / -180..180,
a file that cannot be read or is not UTF-8, or a region named `europe` or
`weekend` stops the run with exit code 2.

## How it works

1. **Discovery.** The cheap calendar endpoint used by older `fli` releases is
   gated, and Google's search page accepts at most **14 airports per request**
   (verified: 4 home + 10 destinations works, 4 + 11 returns an empty page).
   For each distinct departure date and return date, the tool searches batches
   of 10 destination airports with all four home airports batched in, and keeps
   the cheapest price per airport and date. This is where most requests go:
   `(depart dates + return dates) × batches`.
2. **Shortlist.** Cities are ranked by cheapest observed outbound + cheapest
   observed return, with a per-city cap so one cheap city cannot fill the list.
3. **Confirmation.** For each shortlisted city/date pair, complete searches
   (all city airports × all home airports) are run for both legs. Legs are then
   cross-combined: the cheapest outbound and return per airport pair, summed
   over every home/destination airport combination. Open-jaw is detected at
   both ends.

Because phase 1 only returns the cheapest page rows per batch, its prices are
an estimate, not a provable lower bound. The result is therefore the best of
the confirmed shortlist, not a mathematically proven global optimum. Raise
`--max-candidates` to widen the confirmation pass.

Prices are for the requested cabin and passenger count, in the requested
currency, and are two **separate one-way tickets**: there is no
missed-connection protection and no single-ticket open-jaw fare. Use
`--compare-roundtrip` to see how the combination compares with a
conventional round-trip. With `--airlines`, the `vs RT` reference price still
covers all airlines. In that case, JSON reports an empty
`query.roundtrip_airlines` list alongside the itinerary's `query.airlines`.

In JSON, each `outbound` and `return` object contains `segments`, the number
of flight legs, and `layovers`, a list of objects with `airport` (the arrival
airport of the preceding leg) and `minutes` (time between legs). For direct
flights, `layovers` is empty. Each direction also has a `self_transfer` flag,
and each leg lists its `operating_airline` alongside its selling `airline`.

When a connection involves an airport change, `--verbose` names both
airports, for example `connection LGW→STN 3h · airport change`.

## Google Flights links

Every confirmed itinerary gets a deterministic, offline-built
`https://www.google.com/travel/flights/booking?tfs=…` link. The table shows a
clickable `open`; JSON carries three fields:

| Field | Contents |
| --- | --- |
| `booking_url` | Both legs encoded as one two-segment itinerary (open-jaw included). |
| `outbound_url` | The outbound one-way only. |
| `return_url` | The return one-way only. |

`--best-per-city` uses the best offer's `booking_url`, so each city row links
to the itinerary shown.

A caveat: the tool's total is the sum of **two separately booked one-way
tickets**, while `booking_url` opens both legs as a single Google Flights
itinerary. Google may therefore show a different price, or no through-fare for
mixed-carrier open-jaws. `outbound_url` and `return_url` open the exact
one-ways the displayed price is made of.

## Airport data

`src/flight_search/data/airports.csv` is generated from
[OurAirports](https://ourairports.com/data/): scheduled-service, IATA-coded
airports worldwide, intersected with the airports `fli` can query. The snapshot
holds 3835 airports (3173 medium and large, 662 small).

The default region (`--region europe`) is applied at runtime: Europe
(`continent = EU`, which includes the European part of Russia), North Africa
(`MA, DZ, TN, LY, EG, EH`), Turkey (`TR`) and the Caucasus (`GE, AZ, AM`), plus
all of Greece, Cyprus, Spain and Portugal whatever their OurAirports continent
(Rhodes, Kos, Cyprus, the Canaries). Medium and large airports are used by
default (658); `--include-small` adds 62 smaller scheduled airports.

Curated `metros.toml` groups multi-airport cities so open-jaw works within a
metro (London, Paris, Milan, Rome, Barcelona, Stockholm, Oslo, Istanbul,
Moscow, Frankfurt, Düsseldorf, Munich, Brussels, Basel, Venice, Florence,
Warsaw, Bucharest, Tenerife, Glasgow, Belfast, Alexandria), and provides
display-name fixes for airports whose municipality is a suburb (Zagreb,
Marseille, Nice, Toulouse, Tirana, Skopje, Pristina, …).

Refresh the snapshot from the upstream dataset:

```sh
uv run flight-search refresh-airports
# or: uv run python scripts/refresh_airports.py
```

List the airports in a region:

```sh
uv run flight-search airports --region weekend
```

## Dependency note

This project pins `flights==0.11.1` from PyPI. It fetches Google Flights prices
from the search page.

## Development

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run actionlint
```

`uv run ruff format .` fixes a failing format check. CI runs the same
checks with Python 3.12, the oldest supported version, on every push to
`main` and every pull request. GitHub hides the
formatting commit in its blame view by itself; locally, skip it with:

```sh
git blame --ignore-revs-file .git-blame-ignore-revs <file>
```

The tests cover date expansion, time-window rounding and date-aware arrival
checks, metro grouping, batching, candidate selection and open-jaw
combination — all offline.
