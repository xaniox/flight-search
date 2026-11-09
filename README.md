# flight-search

Weekend-getaway and open-jaw flight search on top of
[`fli`](https://github.com/punitarani/fli) (Google Flights), from the
Karlsruhe area by default.

Given a date range, a set of departure weekdays, a set of return weekdays and
an airport region, it prices every matching weekend and returns the cheapest
**two separate one-way tickets** — including open-jaw combinations such as
outbound `SXB → MXP` and return `LIN → FRA`.

```text
Total  City             Outbound                          Return                            Nights  Stops  Open jaw  Link
€49    Milan (IT)       Fri 20 Nov · SXB→MXP · 12:45–14:15  Sun 22 Nov · LIN→FRA · 17:50–19:55  2       0/0    both      open
€76    Barcelona (ES)   Fri 13 Nov · SXB→BCN · 14:45–16:25  Mon 16 Nov · BCN→SXB · 05:50–07:45  3       0/0    —         open
```

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

## Quick start

Cheapest weekend in all of Europe / North Africa over the next two weeks:
(583 airports — roughly 2–4 minutes on a cold cache)

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
  --return-arrive-before 22:00 \
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
| `--region europe\|weekend` | `europe` = every scheduled airport in Europe + North Africa (583); `weekend` = within `--max-distance-km` of Karlsruhe. |
| `--countries`, `--dest`, `--exclude`, `--include-small` | Narrow or override the destination set. |
| `--depart-days`, `--return-days` | Weekday sets, e.g. `thu,fri` and `sun,mon`. |
| `--start`, `--end` | Date range; both legs must fall inside it. |
| `--min-nights`, `--max-nights` | Trip length constraint. |
| `--depart-after`, `--depart-before` | Optional outbound departure window, local time (`17:30`, `21:15`). |
| `--return-arrive-before` | Optional latest return arrival at the home airport, local time. |
| `--max-stops` | `ANY`, `0`/`NON_STOP`, `1`/`ONE_STOP`, `2+`. |
| `--top`, `--best-per-city`, `--per-city` | Display count and city diversity in the confirmed shortlist. |
| `--compare-roundtrip` | Also price a conventional same-airport round-trip for comparison. |
| `--max-candidates` | How many city/date-pair candidates are confirmed exactly (default 60). |
| `--cache-ttl`, `--no-cache` | Disk cache lifetime (default 12h) in `~/.cache/flight-search`. |
| `--concurrency`, `--max-requests` | Parallelism and a hard request ceiling. |
| `--dry-run` | Print the plan and request estimate without network calls. |

Time windows are optional; when omitted the whole day qualifies. Google's
request format only understands whole hours and its bounds are inclusive of
the whole hour, and the arrival bound is not date-aware. The tool therefore
sends permissive hour bounds and enforces the exact minute (and the same-day
rule, so a Monday 01:00 red-eye does not pass a Sunday 22:00 deadline)
locally on the decoded itineraries.

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
conventional round-trip.

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

`src/flight_search/data/airports_eu_na.csv` is generated from
[OurAirports](https://ourairports.com/data/): scheduled-service, IATA-coded
airports in Europe (`continent = EU`, which includes Russia) and North Africa
(`MA, DZ, TN, LY, EG, EH`), intersected with the airports `fli` can query.
Medium and large airports are used by default (583); `--include-small` adds 59
smaller scheduled airports.

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

`flights==0.9.0` on PyPI talks to `GetShoppingResults`/`GetCalendarGraph`,
which Google now answers with an empty payload. The working page transport is
only on the upstream `main` branch, so `pyproject.toml` pins the commit
`881aee5ff4321e81ea2157cb44be94ce6a21dc1b` (version 0.10.0). Expect the exact
transport to change again; `scripts/refresh_airports.py` and the discovery
batch limit are the two places most likely to need adjusting.

## Development

```sh
uv run pytest
```

The tests cover date expansion, time-window rounding and date-aware arrival
checks, metro grouping, batching, candidate selection and open-jaw
combination — all offline.
