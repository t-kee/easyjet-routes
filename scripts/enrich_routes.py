from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "easyroutes_sources.html"
OUTPUT = ROOT / "data" / "easyjet_routes_enriched.json"
FR24_MERGED = ROOT / "data" / "fr24_merged.json"

AIRPORTS_CSV_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"

# Conservative planning assumptions, not operational truth.
# These are only here to create a useful first approximation until we obtain real schedule data.
DEFAULT_CRUISE_SPEED_KT = 430

TAXI_AND_BUFFER_MINUTES = 30

AIRCRAFT_TYPE_MAP = {
    "319": "A319",
    "A319": "A319",
    "320": "A320",
    "A320": "A320",
    "32A": "A320",
    "A20N": "A320N",
    "A320N": "A320N",
    "32Q": "A320N",
    "321": "A321N",
    "A21N": "A321N",
    "A321N": "A321N",
}


@dataclass(frozen=True)
class Airport:
    iata: str
    name: str
    latitude: float
    longitude: float
    country: str | None = None
    municipality: str | None = None


def main() -> None:
    html = SOURCE.read_text(encoding="utf-8")
    airports_by_iata = load_airports()
    routes = extract_routes_from_easyjet_source_view(html)
    fr24_route_data, fr24_extra_airports, fr24_airports_without_data = load_fr24_route_data()

    routes_by_key = {route["route"]: route for route in routes}
    for route_key, fr24_data in fr24_route_data.items():
        if route_key in routes_by_key:
            continue

        origin_iata, destination_iata = route_key.split("-", 1)
        routes_by_key[route_key] = {
            "route": route_key,
            "origin": {
                "iata": origin_iata,
                "name": fr24_data.get("origin_name") or origin_iata,
            },
            "destination": {
                "iata": destination_iata,
                "name": fr24_data.get("destination_name") or destination_iata,
            },
            "source_url": None,
            "route_source": "FR24 extra route",
        }

    routes = list(routes_by_key.values())

    enriched_routes = []
    missing_coordinates = 0

    for route in routes:
        origin_iata = route["origin"]["iata"]
        destination_iata = route["destination"]["iata"]
        origin_airport = airports_by_iata.get(origin_iata)
        destination_airport = airports_by_iata.get(destination_iata)

        distance_nm = None
        estimated_flight_time_minutes = None
        estimated_block_time_minutes = None

        if origin_airport and destination_airport:
            distance_nm = round(
                haversine_nm(
                    origin_airport.latitude,
                    origin_airport.longitude,
                    destination_airport.latitude,
                    destination_airport.longitude,
                )
            )
            estimated_flight_time_minutes = round(
                distance_nm / DEFAULT_CRUISE_SPEED_KT * 60
            )
            estimated_block_time_minutes = (
                estimated_flight_time_minutes + TAXI_AND_BUFFER_MINUTES
            )
        else:
            missing_coordinates += 1

        enriched_routes.append(
            {
                **route,
                "weekly_frequency": fr24_route_data.get(route["route"], {}).get("weekly_frequency"),
                "weekly_frequency_total_observed": fr24_route_data.get(route["route"], {}).get("weekly_frequency_total_observed"),
                "weekly_frequency_capture_count": fr24_route_data.get(route["route"], {}).get("weekly_frequency_capture_count"),
                "weekly_frequency_source": fr24_route_data.get(route["route"], {}).get("weekly_frequency_source"),
                "aircraft_types": fr24_route_data.get(route["route"], {}).get("aircraft_types", []),
                "fr24_flight_numbers": fr24_route_data.get(route["route"], {}).get("flight_numbers", []),
                "has_fr24_data": route["route"] in fr24_route_data,
                "origin_has_fr24_data": origin_iata not in fr24_airports_without_data,
                "destination_has_fr24_data": destination_iata not in fr24_airports_without_data,
                "is_fr24_extra_airport_route": (
                    origin_iata in fr24_extra_airports or destination_iata in fr24_extra_airports
                ),
                "distance_nm": distance_nm,
                "estimated_flight_time_minutes": estimated_flight_time_minutes,
                "estimated_block_time_minutes": estimated_block_time_minutes,
                "time_estimate_basis": (
                    f"Great-circle distance / {DEFAULT_CRUISE_SPEED_KT} kt + "
                    f"{TAXI_AND_BUFFER_MINUTES} min taxi/buffer"
                    if distance_nm is not None
                    else None
                ),
            }
        )

    enriched_routes.sort(key=lambda r: r["route"])

    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(
        json.dumps(enriched_routes, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    routes_with_fr24_data = sum(1 for route in enriched_routes if route["has_fr24_data"])
    print(f"Wrote {len(enriched_routes)} routes to {OUTPUT}")
    print(f"Routes with FR24 frequency data: {routes_with_fr24_data}")
    print(f"FR24 extra airports: {sorted(fr24_extra_airports)}")
    print(f"Airports without FR24 data: {sorted(fr24_airports_without_data)}")
    if missing_coordinates:
        print(f"Warning: {missing_coordinates} route(s) had missing airport coordinates")


def extract_routes_from_easyjet_source_view(html: str) -> list[dict]:
    """Extract routes from a Chrome 'View Source' saved HTML file.

    The saved file is not the raw easyJet DOM. Chrome wraps escaped tags in spans,
    so the route links look like:
      href="<a ... href="https://www.easyjet.com/en/cheap-flights/...">..."
      &lt;strong&gt;</span>Aberdeen (ABZ)<span ...>...
    """
    pattern = re.compile(
        r'<a class="html-attribute-value html-external-link"[^>]+href="(?P<url>https://www\.easyjet\.com/en/cheap-flights/[^"]+)"[^>]*>[^<]+</a>"&gt;</span>'
        r'<span class="html-tag">&lt;strong&gt;</span>(?P<origin>[^<]+?)<span class="html-tag">&lt;/strong&gt;</span>\s*to\s*'
        r'<span class="html-tag">&lt;strong&gt;</span>(?P<destination>[^<]+?)<span class="html-tag">&lt;/strong&gt;',
        re.DOTALL,
    )

    routes: list[dict] = []
    seen: set[str] = set()

    for match in pattern.finditer(html):
        source_url = unescape(match.group("url")).strip()
        origin = unescape(match.group("origin")).strip()
        destination = unescape(match.group("destination")).strip()

        origin_match = re.match(r"(.+?) \(([A-Z]{3})\)", origin)
        destination_match = re.match(r"(.+?) \(([A-Z]{3})\)", destination)

        if not origin_match or not destination_match:
            continue

        origin_name, origin_iata = origin_match.groups()
        destination_name, destination_iata = destination_match.groups()
        key = f"{origin_iata}-{destination_iata}"

        if key in seen:
            continue
        seen.add(key)

        routes.append(
            {
                "route": key,
                "origin": {"iata": origin_iata, "name": origin_name},
                "destination": {"iata": destination_iata, "name": destination_name},
                "source_url": source_url,
            }
        )

    return routes


def load_fr24_route_data() -> tuple[dict[str, dict], set[str], set[str]]:
    """Load manually collected FR24 data and convert it to route-level frequency data.

    `merge_fr24_data.py` produces `data/fr24_merged.json` with this shape:
    {
      "airports": {"LGW": {...}},
      "coverage": {...}
    }

    For a selected airport LGW:
    - departures create LGW-XXX routes
    - arrivals create XXX-LGW routes
    """
    if not FR24_MERGED.exists():
        return {}, set(), set()

    data = json.loads(FR24_MERGED.read_text(encoding="utf-8"))
    selected_airports = data.get("airports", {}) if isinstance(data, dict) else {}
    coverage = data.get("coverage", {}) if isinstance(data, dict) else {}
    metadata = data.get("metadata", {}) if isinstance(data, dict) else {}
    capture_count = metadata.get("capture_count", 1) if isinstance(metadata, dict) else 1
    if not isinstance(capture_count, (int, float)) or capture_count <= 0:
        capture_count = 1

    route_data: dict[str, dict] = {}

    if isinstance(selected_airports, dict):
        for selected_iata, airport_payload in selected_airports.items():
            if not isinstance(selected_iata, str) or not isinstance(airport_payload, dict):
                continue

            selected_iata = selected_iata.upper()

            parse_fr24_direction(
                route_data=route_data,
                selected_iata=selected_iata,
                direction_payload=airport_payload.get("departures", {}),
                is_departure=True,
            )
            parse_fr24_direction(
                route_data=route_data,
                selected_iata=selected_iata,
                direction_payload=airport_payload.get("arrivals", {}),
                is_departure=False,
            )

    fr24_extra_airports = set(coverage.get("fr24_extra_airports", []))
    fr24_airports_without_data = set(
        coverage.get("easyjet_airports_without_fr24_data", [])
    )

    for value in route_data.values():
        total_frequency = value["weekly_frequency"]
        value["weekly_frequency_total_observed"] = total_frequency
        value["weekly_frequency_capture_count"] = capture_count
        value["weekly_frequency"] = round(total_frequency / capture_count, 1)
        value["weekly_frequency_source"] = (
            f"FR24 next 7 days manual browser collection, averaged over {capture_count} capture(s)"
        )
        value["aircraft_types"] = sorted(value["aircraft_types"])
        value["flight_numbers"] = sorted(value["flight_numbers"])

    return route_data, fr24_extra_airports, fr24_airports_without_data


def parse_fr24_direction(
    route_data: dict[str, dict],
    selected_iata: str,
    direction_payload: object,
    is_departure: bool,
) -> None:
    if not isinstance(direction_payload, dict):
        return

    for country_payload in direction_payload.values():
        if not isinstance(country_payload, dict):
            continue

        airports = country_payload.get("airports", {})
        if not isinstance(airports, dict):
            continue

        for other_iata, airport_payload in airports.items():
            if not isinstance(other_iata, str) or not isinstance(airport_payload, dict):
                continue

            other_iata = other_iata.upper()
            route_key = (
                f"{selected_iata}-{other_iata}"
                if is_departure
                else f"{other_iata}-{selected_iata}"
            )

            route_entry = route_data.setdefault(
                route_key,
                {
                    "weekly_frequency": 0,
                    "weekly_frequency_source": "FR24 next 7 days manual browser collection",
                    "aircraft_types": set(),
                    "flight_numbers": set(),
                    "origin_name": selected_iata if is_departure else airport_payload.get("name"),
                    "destination_name": airport_payload.get("name") if is_departure else selected_iata,
                },
            )

            if is_departure:
                route_entry["destination_name"] = airport_payload.get("name") or route_entry.get("destination_name")
            else:
                route_entry["origin_name"] = airport_payload.get("name") or route_entry.get("origin_name")

            flights = airport_payload.get("flights", {})
            if not isinstance(flights, dict):
                continue

            for flight_number, flight_payload in flights.items():
                if isinstance(flight_number, str):
                    route_entry["flight_numbers"].add(flight_number)

                if not isinstance(flight_payload, dict):
                    continue

                utc_days = flight_payload.get("utc", {})
                if not isinstance(utc_days, dict):
                    continue

                for day_payload in utc_days.values():
                    route_entry["weekly_frequency"] += 1
                    if isinstance(day_payload, dict):
                        aircraft = normalize_aircraft_type(day_payload.get("aircraft"))
                        if aircraft:
                            route_entry["aircraft_types"].add(aircraft)


def normalize_aircraft_type(value: object) -> str | None:
    if value is None:
        return None

    raw = str(value).strip().upper()
    if not raw:
        return None

    return AIRCRAFT_TYPE_MAP.get(raw)


def load_airports() -> dict[str, Airport]:
    with urlopen(AIRPORTS_CSV_URL, timeout=30) as response:
        csv_text = response.read().decode("utf-8")

    reader = csv.DictReader(csv_text.splitlines())
    airports: dict[str, Airport] = {}

    for row in reader:
        iata = row.get("iata_code", "").strip()
        if not iata:
            continue

        latitude = parse_float(row.get("latitude_deg"))
        longitude = parse_float(row.get("longitude_deg"))
        if latitude is None or longitude is None:
            continue

        airports[iata] = Airport(
            iata=iata,
            name=row.get("name", "").strip(),
            latitude=latitude,
            longitude=longitude,
            country=row.get("iso_country", "").strip() or None,
            municipality=row.get("municipality", "").strip() or None,
        )

    return airports


def parse_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_nm = 3440.065
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return earth_radius_nm * c


if __name__ == "__main__":
    main()