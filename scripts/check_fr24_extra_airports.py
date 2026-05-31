import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

ROUTES_JSON = ROOT / "data" / "easyjet_routes_enriched.json"

FR24_FILES = [
    ROOT / "data" / "fr24_raw" / "fr24_easyjet_routes_part1.json",
    ROOT / "data" / "fr24_raw" / "fr24_easyjet_routes_part2.json",
]


def collect_fr24_airports_from_direction(direction_data: Any) -> set[str]:
    airports: set[str] = set()

    if not isinstance(direction_data, dict):
        return airports

    for country_data in direction_data.values():
        if not isinstance(country_data, dict):
            continue

        country_airports = country_data.get("airports", {})
        if not isinstance(country_airports, dict):
            continue

        airports.update(country_airports.keys())

    return airports


def normalize_fr24_file_payload(data: Any) -> dict[str, Any]:
    """Accept both supported FR24 dump formats.

    Supported formats:
    1. Direct format:
       {
         "LGW": {"arrivals": {...}, "departures": {...}},
         "MXP": {"arrivals": {...}, "departures": {...}}
       }

    2. Wrapped format:
       {
         "collected_at": "...",
         "source": "...",
         "results": {
           "LGW": {"arrivals": {...}, "departures": {...}}
         }
       }
    """
    if isinstance(data, dict) and isinstance(data.get("results"), dict):
        return data["results"]

    if isinstance(data, dict):
        return data

    return {}


with open(ROUTES_JSON, encoding="utf-8") as f:
    routes = json.load(f)

easyjet_airports: set[str] = set()
for route in routes:
    easyjet_airports.add(route["origin"]["iata"])
    easyjet_airports.add(route["destination"]["iata"])

fr24_airports: set[str] = set()
malformed_entries: list[str] = []

for file in FR24_FILES:
    with open(file, encoding="utf-8") as f:
        raw_data = json.load(f)

    data = normalize_fr24_file_payload(raw_data)

    for selected_iata, selected_data in data.items():
        if not isinstance(selected_iata, str):
            continue

        if not isinstance(selected_data, dict):
            malformed_entries.append(f"{file.name}:{selected_iata} -> {type(selected_data).__name__}")
            continue

        fr24_airports.add(selected_iata)

        fr24_airports |= collect_fr24_airports_from_direction(
            selected_data.get("arrivals", {})
        )
        fr24_airports |= collect_fr24_airports_from_direction(
            selected_data.get("departures", {})
        )

extra_in_fr24 = sorted(fr24_airports - easyjet_airports)
missing_from_fr24 = sorted(easyjet_airports - fr24_airports)

print(f"easyJet source airports: {len(easyjet_airports)}")
print(f"FR24 airports found: {len(fr24_airports)}")
print()

print(f"Extra in FR24: {len(extra_in_fr24)}")
print(extra_in_fr24)
print()

print(f"Missing from FR24: {len(missing_from_fr24)}")
print(missing_from_fr24)

if malformed_entries:
    print()
    print(f"Ignored malformed entries: {len(malformed_entries)}")
    for entry in malformed_entries[:20]:
        print(f"- {entry}")
    if len(malformed_entries) > 20:
        print(f"... and {len(malformed_entries) - 20} more")