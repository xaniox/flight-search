"""Local browser adapter for the weekend search."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import date
from pathlib import Path
from threading import Lock, Thread
from time import monotonic
from uuid import uuid4

from flask import Flask, jsonify, redirect, request
from werkzeug.exceptions import RequestEntityTooLarge, SecurityError

from flight_search.airports import AirportDataError, load_airports
from flight_search.cache import Cache
from flight_search.destinations import BrowserDestinationChoice, DestinationChoice
from flight_search.fli_api import RequestBudget
from flight_search.search import SearchResult, confirm_more, run_search
from flight_search.settings_file import BUILT_IN_REGIONS
from flight_search.web_results import (
    OutboundProjection,
    pair_results,
    pending_by_city,
    project_outbound_choices,
)
from flight_search.weekend import WeekendQuery, prepare_weekend

logger = logging.getLogger(__name__)

_LIST_FIELDS = frozenset({"home", "depart_days", "return_days", "airline_codes"})
_TIME_FIELDS = frozenset(
    {"depart_after", "depart_before", "return_depart_after", "return_arrive_before"}
)
_INT_FIELDS = frozenset({"min_nights", "max_nights", "max_requests"})


class _SearchRun:
    """Thread-safe progress and terminal outcome for one search."""

    def __init__(self, cache: Cache | None = None) -> None:
        self._lock = Lock()
        self.loading = Lock()
        self.cache = cache
        self.result: SearchResult | None = None
        self._outbound: OutboundProjection | None = None
        self._state = {"status": "running", "phase": "Preparing", "done": 0, "total": 0}

    def start(self, description: str, total: int) -> Callable[[int], None]:
        with self._lock:
            self._state.update(phase=description, done=0, total=total)

        def update(done: int) -> None:
            with self._lock:
                self._state["done"] = done

        return update

    def stop(self) -> None:
        pass

    def discovered(self, failures: Sequence[str]) -> None:
        if failures:
            with self._lock:
                self._state["discovery_failures"] = len(failures)

    def finish(
        self,
        *,
        outbound: OutboundProjection | None = None,
        result_source: SearchResult | None = None,
        **state,
    ) -> None:
        with self._lock:
            self._state = state
            self._outbound = outbound
            self.result = result_source

    def replace_result(
        self, result: SearchResult, payload: dict, outbound: OutboundProjection
    ) -> None:
        with self._lock:
            self._state = {**self._state, "result": payload}
            self._outbound = outbound
            self.result = result

    def booking_url(self, outbound_id: str, return_id: str) -> str | None:
        with self._lock:
            projection = self._outbound
        if projection is None:
            return None
        return projection.booking_url(outbound_id, return_id)

    def snapshot(self) -> dict:
        with self._lock:
            return self._state.copy()


def _result_payload(result, settings, per_city: int):
    """The browser payload of a search result and its booking projection."""
    payload = pair_results(result, settings)
    outbound = (
        project_outbound_choices(result)
        if isinstance(result, SearchResult)
        else OutboundProjection(settings)
    )
    payload["outbound_choices"] = outbound.payload()
    payload["per_city"] = per_city
    payload["currency"] = settings.currency
    payload["pending"] = (
        pending_by_city(result, per_city) if isinstance(result, SearchResult) else {}
    )
    return payload, outbound


def _json_defaults(
    defaults: WeekendQuery, configured_regions: Mapping[str, frozenset[str]]
) -> dict:
    fields = {
        name: getattr(defaults, name)
        for name in _TIME_FIELDS | _INT_FIELDS | {"start", "end", "allow_codeshare"}
    }
    for name in _LIST_FIELDS:
        fields[name] = [
            token
            for value in getattr(defaults, name)
            for token in value.replace(",", " ").split()
        ]
    fields["airline_codes"] = [code.upper() for code in fields["airline_codes"]]

    choice = defaults.destination
    regions = []
    countries = sorted(choice.countries)
    preset = None
    if isinstance(choice, BrowserDestinationChoice):
        regions = list(choice.regions)
    elif choice.codes or (choice.region == "weekend" and countries):
        preset_id = "@configured"
        while preset_id in configured_regions:
            preset_id += "@"
        caption = (
            ", ".join(choice.codes)
            if choice.codes
            else (f"Wochenendumkreis · {', '.join(countries)}")
        )
        preset = {"id": preset_id, "label": f"Voreinstellung · {caption}"}
        regions = [preset_id]
        countries = []
    elif configured_regions.get(choice.region) == choice.countries:
        regions = [choice.region]
        countries = []
    elif choice.region == "weekend" or not countries:
        regions = [choice.region]
    return {
        **fields,
        "regions": regions,
        "countries": countries,
        "configured_destination": preset,
    }


def _parse_fields(
    fields: dict,
    defaults: WeekendQuery,
    configured_regions: Mapping[str, frozenset[str]],
    default_fields: dict,
) -> WeekendQuery:
    changes = {}
    for name, value in fields.items():
        if name in _LIST_FIELDS or name in {"regions", "countries"}:
            if not isinstance(value, list) or not all(
                isinstance(item, str) and item.strip() for item in value
            ):
                raise ValueError(f"{name} must be a list of non-empty strings.")
            changes[name] = tuple(item.strip() for item in value)
        elif name in {"start", "end"}:
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a date string.")
            changes[name] = value
        elif name in _TIME_FIELDS:
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{name} must be a time string or null.")
            changes[name] = value
        elif name in _INT_FIELDS:
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} must be a non-negative integer.")
            changes[name] = value
        elif name == "allow_codeshare":
            if not isinstance(value, bool):
                raise ValueError(f"{name} must be true or false.")
            changes[name] = value
        else:
            raise ValueError(f"Unknown search field: {name}.")

    if "home" in changes:
        changes["home"] = tuple(dict.fromkeys(code.upper() for code in changes["home"]))
    if {"regions", "countries"} & changes.keys():
        source = defaults.destination
        regions = changes.pop("regions", default_fields["regions"])
        preset = default_fields["configured_destination"]
        preset_id = preset["id"] if preset else None
        changes["destination"] = BrowserDestinationChoice(
            regions=tuple(region for region in regions if region != preset_id),
            configured_default=source
            if isinstance(source, DestinationChoice) and preset_id in regions
            else None,
            countries=frozenset(
                code.upper()
                for code in changes.pop("countries", default_fields["countries"])
            ),
            configured_regions=configured_regions,
            max_distance_km=source.max_distance_km,
            include_small=source.include_small,
            exclude_codes=source.exclude_codes,
            exclude_countries=source.exclude_countries,
        )
    return replace(defaults, **changes)


def create_app(
    defaults: WeekendQuery,
    *,
    configured_regions: Mapping[str, frozenset[str]],
    search_runner=run_search,
    airport_loader=load_airports,
    cache_dir: Path | None = None,
    cache_ttl: str = "12h",
    cache_enabled: bool = True,
    rolling_dates: bool = False,
) -> Flask:
    """Create the loopback application and its in-process search registry."""
    app = Flask(__name__, static_folder="web_assets", static_url_path="/assets")
    app.config.update(
        MAX_CONTENT_LENGTH=16 * 1024, TRUSTED_HOSTS=["localhost", "127.0.0.1"]
    )
    configured_regions = dict(configured_regions)
    default_fields = _json_defaults(defaults, configured_regions)
    runs: dict[str, _SearchRun] = {}
    runs_lock = Lock()
    if rolling_dates:
        window = date.fromisoformat(defaults.end) - date.fromisoformat(defaults.start)

    def current_defaults(today: date) -> WeekendQuery:
        if not rolling_dates:
            return defaults
        return replace(
            defaults,
            start=today.isoformat(),
            end=(today + window).isoformat(),
        )

    def same_origin() -> bool:
        origin = request.headers.get("Origin")
        return origin is None or origin == request.host_url.rstrip("/")

    @app.errorhandler(RequestEntityTooLarge)
    def oversized_request(_error):
        return jsonify(error="Search request is too large."), 413

    @app.errorhandler(SecurityError)
    def untrusted_host(_error):
        return jsonify(error="Use the local flight-search address."), 400

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    @app.get("/api/catalogs")
    def catalogs():
        from fli.models import Airline

        try:
            airports = airport_loader(include_small=True)
        except AirportDataError as exc:
            return jsonify(error=str(exc)), 500

        query_defaults = current_defaults(date.today())
        region_ids = [*BUILT_IN_REGIONS, *configured_regions]
        if preset := default_fields["configured_destination"]:
            region_ids.insert(0, preset["id"])
        return jsonify(
            airports=[
                {"code": a.iata, "name": a.name, "city": a.city, "country": a.country}
                for a in airports
            ],
            regions=region_ids,
            countries=sorted({airport.country for airport in airports}),
            airlines=[
                {"code": item.name.removeprefix("_"), "name": item.value}
                for item in Airline
            ],
            defaults={
                **default_fields,
                "start": query_defaults.start,
                "end": query_defaults.end,
            },
        )

    @app.post("/api/searches")
    def start_search():
        if not same_origin():
            return jsonify(
                error="Searches must start from the local flight-search page."
            ), 403

        fields = request.get_json(silent=True)
        if not isinstance(fields, dict):
            return jsonify(error="Send a JSON object with search fields."), 400
        try:
            today = date.today()
            query = _parse_fields(
                fields, current_defaults(today), configured_regions, default_fields
            )
            plan = prepare_weekend(
                query,
                today=today,
                airport_loader=airport_loader,
                enforce_budget=True,
            )
            cache, budget = plan.create_resources(
                cache_dir=cache_dir, cache_ttl=cache_ttl, cache_enabled=cache_enabled
            )
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except AirportDataError as exc:
            return jsonify(error=str(exc)), 500

        search_id = uuid4().hex
        run = _SearchRun(cache)
        with runs_lock:
            runs[search_id] = run

        def execute() -> None:
            started = monotonic()
            search_request = plan.request
            logger.debug(
                "Plan: %s · %s to %s · %d date pairs, %d destinations · "
                "%d per batch · estimated requests: %d (budget: %d) · cache: %s",
                ", ".join(search_request.home),
                plan.start,
                plan.end,
                len(search_request.pairs),
                len(search_request.destinations),
                search_request.batch_size,
                plan.estimated_requests,
                plan.max_requests,
                "enabled" if cache.active else "disabled",
            )
            try:
                result = search_runner(
                    search_request, cache=cache, budget=budget, progress=run
                )
                results, outbound = _result_payload(
                    result, search_request.settings, search_request.per_city
                )
                warnings = plan.warnings
                failures = run.snapshot().get("discovery_failures", 0)
                if failures:
                    warnings += (
                        f"{failures} discovery requests failed. Results may be incomplete.",
                    )
                logger.debug(
                    "Finished in %.0f ms · confirmed pairs: %d · requests: %d · "
                    "cache: %d hits, %d misses, %d writes · discovery failures: %d",
                    (monotonic() - started) * 1000,
                    len(results["pairs"]),
                    budget.used,
                    cache.stats.hits,
                    cache.stats.misses,
                    cache.stats.writes,
                    failures,
                )
                run.finish(
                    status="done",
                    result=results,
                    outbound=outbound,
                    result_source=result if isinstance(result, SearchResult) else None,
                    warnings=warnings,
                )
            except Exception as exc:
                logger.exception("Browser search failed")
                run.finish(status="error", error=str(exc) or type(exc).__name__)

        Thread(target=execute, name=f"search-{search_id[:8]}", daemon=True).start()
        return jsonify(id=search_id), 202

    @app.get("/api/searches/<search_id>")
    def search_state(search_id: str):
        with runs_lock:
            run = runs.get(search_id)
        if run is None:
            return jsonify(error="Search not found."), 404
        return jsonify(run.snapshot())

    @app.post("/api/searches/<search_id>/cities/<path:city_key>/more")
    def load_more(search_id: str, city_key: str):
        if not same_origin():
            return jsonify(
                error="Load requests must come from the local flight-search page."
            ), 403
        with runs_lock:
            run = runs.get(search_id)
        if run is None:
            return jsonify(error="Search not found."), 404
        state = run.snapshot()
        status = state["status"]
        if status == "running":
            return jsonify(error="The search has not finished yet."), 409
        if status != "done" or run.result is None:
            return jsonify(error="The search failed, so there is nothing to load."), 409
        with run.loading:
            current = run.result
            budget = RequestBudget(None)
            try:
                result = confirm_more(
                    current,
                    city_key,
                    current.request.per_city,
                    cache=run.cache,
                    budget=budget,
                )
                payload, outbound = _result_payload(
                    result, result.request.settings, result.request.per_city
                )
            except Exception as exc:
                logger.exception("Loading more pairs failed")
                return jsonify(error=str(exc) or type(exc).__name__), 500
            finally:
                pending_city = state["result"]["pending"].get(city_key, {})
                city = pending_city.get("city", city_key)
                logger.debug("Load more for %s · requests: %d", city, budget.used)
            run.replace_result(result, payload, outbound)
        return jsonify(payload)

    @app.get("/api/searches/<search_id>/booking")
    def booking(search_id: str):
        with runs_lock:
            run = runs.get(search_id)
        outbound_id = request.args.get("outbound", "")
        return_id = request.args.get("return", "")
        try:
            url = run.booking_url(outbound_id, return_id) if run else None
        except Exception:
            logger.exception("Could not create combined booking link")
            return jsonify(error="The booking link could not be generated."), 500
        if url is None:
            return jsonify(error="This flight combination was not found."), 404
        return redirect(url)

    return app
