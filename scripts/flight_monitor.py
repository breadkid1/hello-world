#!/usr/bin/env python3
"""Monitor flight prices for a 9-day Nanjing/Shanghai to Urumqi trip.

The script uses the Amadeus Self-Service Flight Offers API. Set these
environment variables before running real searches:

    AMADEUS_CLIENT_ID=...
    AMADEUS_CLIENT_SECRET=...

Run `python scripts/flight_monitor.py --dry-run` to generate a report from
sample data without credentials.
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

AMADEUS_TEST_AUTH_URL = "https://test.api.amadeus.com/v1/security/oauth2/token"
AMADEUS_TEST_OFFERS_URL = "https://test.api.amadeus.com/v2/shopping/flight-offers"
AMADEUS_PROD_AUTH_URL = "https://api.amadeus.com/v1/security/oauth2/token"
AMADEUS_PROD_OFFERS_URL = "https://api.amadeus.com/v2/shopping/flight-offers"


@dataclasses.dataclass(frozen=True)
class SearchPlan:
    outbound_origin: str
    outbound_destination: str
    outbound_date: str
    return_origin: str
    return_destination: str
    return_date: str


@dataclasses.dataclass(frozen=True)
class LegOffer:
    origin: str
    destination: str
    departure_date: str
    total_price: float
    currency: str
    adults: int
    departure_at: str
    arrival_at: str
    validating_airline: str
    raw_offer_id: str


@dataclasses.dataclass(frozen=True)
class TripOffer:
    outbound_origin: str
    outbound_destination: str
    outbound_date: str
    return_origin: str
    return_destination: str
    return_date: str
    total_price: float
    currency: str
    adults: int
    price_per_adult: float
    outbound_departure: str
    outbound_arrival: str
    return_departure: str
    return_arrival: str
    validating_airline: str
    raw_offer_id: str


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def build_search_plans(config: dict[str, Any]) -> list[SearchPlan]:
    plans: list[SearchPlan] = []
    for origin in config["outbound"]["origins"]:
        for outbound_date in config["outbound"]["dates"]:
            return_date = (
                dt.date.fromisoformat(outbound_date)
                + dt.timedelta(days=int(config["return"]["days_after_outbound"]))
            ).isoformat()
            plans.append(
                SearchPlan(
                    outbound_origin=origin,
                    outbound_destination=config["outbound"]["destination"],
                    outbound_date=outbound_date,
                    return_origin=config["return"]["origin"],
                    return_destination=config["return"]["destination"],
                    return_date=return_date,
                )
            )
    return plans


def http_post_form(url: str, data: dict[str, str]) -> dict[str, Any]:
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=encoded,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def http_get_json(url: str, params: dict[str, Any], token: str) -> dict[str, Any]:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{url}?{query}",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        return json.loads(response.read().decode("utf-8"))


def get_access_token(client_id: str, client_secret: str, production: bool) -> str:
    auth_url = AMADEUS_PROD_AUTH_URL if production else AMADEUS_TEST_AUTH_URL
    payload = http_post_form(
        auth_url,
        {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
    )
    return str(payload["access_token"])


def query_one_way(
    origin: str,
    destination: str,
    departure_date: str,
    config: dict[str, Any],
    token: str,
    production: bool,
) -> dict[str, Any]:
    offers_url = AMADEUS_PROD_OFFERS_URL if production else AMADEUS_TEST_OFFERS_URL
    params = {
        "originLocationCode": origin,
        "destinationLocationCode": destination,
        "departureDate": departure_date,
        "adults": int(config["adults"]),
        "currencyCode": config.get("currency", "CNY"),
        "max": int(config.get("max_results_per_search", 20)),
    }
    return http_get_json(offers_url, params, token)


def segment_time(offer: dict[str, Any], key: str) -> str:
    segments = offer.get("itineraries", [{}])[0].get("segments", [])
    if not segments:
        return ""
    segment = segments[0] if key == "departure" else segments[-1]
    return str(segment[key]["at"])


def validating_airline(offer: dict[str, Any]) -> str:
    pricing_options = offer.get("validatingAirlineCodes") or []
    if pricing_options:
        return str(pricing_options[0])
    segments = offer.get("itineraries", [{}])[0].get("segments", [])
    if segments:
        return str(segments[0].get("carrierCode", ""))
    return ""


def parse_leg_offers(
    origin: str,
    destination: str,
    departure_date: str,
    config: dict[str, Any],
    payload: dict[str, Any],
) -> list[LegOffer]:
    offers: list[LegOffer] = []
    adults = int(config["adults"])
    currency = config.get("currency", "CNY")
    for offer in payload.get("data", []):
        price = float(offer["price"]["total"])
        offers.append(
            LegOffer(
                origin=origin,
                destination=destination,
                departure_date=departure_date,
                total_price=price,
                currency=str(offer["price"].get("currency", currency)),
                adults=adults,
                departure_at=segment_time(offer, "departure"),
                arrival_at=segment_time(offer, "arrival"),
                validating_airline=validating_airline(offer),
                raw_offer_id=str(offer.get("id", "")),
            )
        )
    return sorted(offers, key=lambda offer: (offer.total_price, offer.departure_at))


def combine_legs(outbound: LegOffer, inbound: LegOffer) -> TripOffer:
    total = outbound.total_price + inbound.total_price
    airline = "/".join(part for part in [outbound.validating_airline, inbound.validating_airline] if part)
    raw_id = "/".join(part for part in [outbound.raw_offer_id, inbound.raw_offer_id] if part)
    return TripOffer(
        outbound_origin=outbound.origin,
        outbound_destination=outbound.destination,
        outbound_date=outbound.departure_date,
        return_origin=inbound.origin,
        return_destination=inbound.destination,
        return_date=inbound.departure_date,
        total_price=total,
        currency=outbound.currency,
        adults=outbound.adults,
        price_per_adult=round(total / outbound.adults, 2),
        outbound_departure=outbound.departure_at,
        outbound_arrival=outbound.arrival_at,
        return_departure=inbound.departure_at,
        return_arrival=inbound.arrival_at,
        validating_airline=airline,
        raw_offer_id=raw_id,
    )


def is_morning_departure(offer: TripOffer, cutoff: str) -> bool:
    if not offer.outbound_departure:
        return False
    departure_time = dt.datetime.fromisoformat(offer.outbound_departure).time()
    cutoff_time = dt.time.fromisoformat(cutoff)
    return departure_time <= cutoff_time


def dry_run_offers(config: dict[str, Any]) -> list[TripOffer]:
    plans = build_search_plans(config)
    sample_prices = [4890, 5280, 5560, 6020, 5190, 5750]
    offers: list[TripOffer] = []
    for idx, plan in enumerate(plans):
        outbound_hour = 8 + idx % 3
        return_hour = 13 + idx % 5
        price = float(sample_prices[idx % len(sample_prices)] + (idx // len(sample_prices)) * 130)
        offers.append(
            TripOffer(
                outbound_origin=plan.outbound_origin,
                outbound_destination=plan.outbound_destination,
                outbound_date=plan.outbound_date,
                return_origin=plan.return_origin,
                return_destination=plan.return_destination,
                return_date=plan.return_date,
                total_price=price,
                currency=config.get("currency", "CNY"),
                adults=int(config["adults"]),
                price_per_adult=round(price / int(config["adults"]), 2),
                outbound_departure=f"{plan.outbound_date}T{outbound_hour:02d}:30:00",
                outbound_arrival=f"{plan.outbound_date}T{13 + idx % 3:02d}:25:00",
                return_departure=f"{plan.return_date}T{return_hour:02d}:10:00",
                return_arrival=f"{plan.return_date}T{18 + idx % 5:02d}:30:00",
                validating_airline="DRY/DRY",
                raw_offer_id=f"dry-run-out-{idx + 1}/dry-run-back-{idx + 1}",
            )
        )
    return offers


def collect_offers(config: dict[str, Any], production: bool) -> list[TripOffer]:
    client_id = os.environ.get("AMADEUS_CLIENT_ID")
    client_secret = os.environ.get("AMADEUS_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("Missing AMADEUS_CLIENT_ID or AMADEUS_CLIENT_SECRET")

    token = get_access_token(client_id, client_secret, production)
    collected: list[TripOffer] = []
    return_cache: dict[tuple[str, str, str], list[LegOffer]] = {}
    for plan in build_search_plans(config):
        try:
            outbound_payload = query_one_way(
                plan.outbound_origin,
                plan.outbound_destination,
                plan.outbound_date,
                config,
                token,
                production,
            )
            outbound_options = parse_leg_offers(
                plan.outbound_origin,
                plan.outbound_destination,
                plan.outbound_date,
                config,
                outbound_payload,
            )[:3]
            return_key = (plan.return_origin, plan.return_destination, plan.return_date)
            if return_key not in return_cache:
                return_payload = query_one_way(
                    plan.return_origin,
                    plan.return_destination,
                    plan.return_date,
                    config,
                    token,
                    production,
                )
                return_cache[return_key] = parse_leg_offers(
                    plan.return_origin,
                    plan.return_destination,
                    plan.return_date,
                    config,
                    return_payload,
                )[:3]
                time.sleep(0.25)
            for outbound in outbound_options:
                for inbound in return_cache[return_key]:
                    if outbound.currency == inbound.currency:
                        collected.append(combine_legs(outbound, inbound))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            print(f"Warning: {plan} returned HTTP {exc.code}: {body}", file=sys.stderr)
        time.sleep(0.25)
    return collected


def sorted_relevant_offers(offers: list[TripOffer], config: dict[str, Any]) -> list[TripOffer]:
    cutoff = config.get("morning_departure_before", "12:00")
    morning = [offer for offer in offers if is_morning_departure(offer, cutoff)]
    selected = morning if morning else offers
    return sorted(selected, key=lambda offer: (offer.total_price, offer.outbound_departure))


def write_report(config: dict[str, Any], offers: list[TripOffer], dry_run: bool) -> None:
    report_path = Path(config["report_path"])
    report_path.parent.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC")
    selected = sorted_relevant_offers(offers, config)
    lines = [
        f"# {config['trip_name']} flight monitor",
        "",
        f"Generated: {now}",
        f"Mode: {'dry run sample data' if dry_run else 'live Amadeus API data'}",
        f"Passengers: {config['adults']} adults",
        f"Outbound morning cutoff: {config.get('morning_departure_before', '12:00')}",
        "",
    ]
    if not selected:
        lines.extend([
            "No offers found for the configured dates and routes.",
            "",
            "Check API coverage, credentials, and whether the airline inventory has opened for these dates.",
        ])
    else:
        best = selected[0]
        lines.extend([
            "## Best current option",
            "",
            (
                f"{best.outbound_origin} → {best.outbound_destination} on {best.outbound_date}, "
                f"return {best.return_origin} → {best.return_destination} on {best.return_date}: "
                f"{best.currency} {best.total_price:.2f} total "
                f"({best.currency} {best.price_per_adult:.2f} per adult)."
            ),
            "",
            "## Ranked options",
            "",
            "| Rank | Route | Dates | Price total | Per adult | Outbound | Return | Airline |",
            "| --- | --- | --- | ---: | ---: | --- | --- | --- |",
        ])
        for rank, offer in enumerate(selected[:25], start=1):
            route = f"{offer.outbound_origin}→{offer.outbound_destination} / {offer.return_origin}→{offer.return_destination}"
            dates = f"{offer.outbound_date} to {offer.return_date}"
            lines.append(
                f"| {rank} | {route} | {dates} | {offer.currency} {offer.total_price:.2f} | "
                f"{offer.currency} {offer.price_per_adult:.2f} | {offer.outbound_departure} | "
                f"{offer.return_departure} | {offer.validating_airline} |"
            )
    lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")


def append_history(config: dict[str, Any], offers: list[TripOffer], dry_run: bool) -> None:
    history_path = Path(config["history_path"])
    history_path.parent.mkdir(parents=True, exist_ok=True)
    exists = history_path.exists()
    timestamp = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    fields = [
        "checked_at",
        "mode",
        "outbound_origin",
        "outbound_destination",
        "outbound_date",
        "return_origin",
        "return_destination",
        "return_date",
        "total_price",
        "currency",
        "adults",
        "price_per_adult",
        "outbound_departure",
        "return_departure",
        "validating_airline",
        "raw_offer_id",
    ]
    with history_path.open("a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        if not exists:
            writer.writeheader()
        for offer in sorted_relevant_offers(offers, config):
            writer.writerow({
                "checked_at": timestamp,
                "mode": "dry-run" if dry_run else "live",
                "outbound_origin": offer.outbound_origin,
                "outbound_destination": offer.outbound_destination,
                "outbound_date": offer.outbound_date,
                "return_origin": offer.return_origin,
                "return_destination": offer.return_destination,
                "return_date": offer.return_date,
                "total_price": f"{offer.total_price:.2f}",
                "currency": offer.currency,
                "adults": offer.adults,
                "price_per_adult": f"{offer.price_per_adult:.2f}",
                "outbound_departure": offer.outbound_departure,
                "return_departure": offer.return_departure,
                "validating_airline": offer.validating_airline,
                "raw_offer_id": offer.raw_offer_id,
            })


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor NKG/SHA/PVG to URC flight offers.")
    parser.add_argument("--config", default="flight_monitor_config.json", help="Path to JSON config file.")
    parser.add_argument("--dry-run", action="store_true", help="Use sample offers instead of the live API.")
    parser.add_argument("--production", action="store_true", help="Use the Amadeus production API instead of test API.")
    args = parser.parse_args()

    config = load_config(Path(args.config))
    offers = dry_run_offers(config) if args.dry_run else collect_offers(config, args.production)
    write_report(config, offers, args.dry_run)
    append_history(config, offers, args.dry_run)
    print(f"Wrote {config['report_path']} and appended {config['history_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
