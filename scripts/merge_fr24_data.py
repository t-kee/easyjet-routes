

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
FR24_DIR = DATA_DIR / "fr24_raw"

ROUTES_JSON = DATA_DIR / "easyjet_routes_enriched.json"

PART_FILES = [
    FR24_DIR / "fr24_easyjet_routes_part1.json",
    FR24_DIR / "fr24_easyjet_routes_part2.json",
]

OUTPUT_FILE = DATA_DIR / "fr24_merged.json"
COVERAGE_REPORT_FILE = DATA_DIR / "fr24_coverage_report.json"


def load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def normalize_fr24_file_payload(data: Any) -> dict[str, Any]:
    """Accept both direct and wrapped FR24 dump formats."""
    if isinstance(data, dict) and isinstance(data.get("results"), dict):
        return data["results"]

    if isinstance(data, dict):
        return data

    return {}


def collect_easyjet_source_airports() -> set[str]:
    if not ROUTES_JSON.exists():
        raise FileNotFoundError(
            f"Could not find {ROUTES_JSON}. Run scripts/enrich_routes.py first."
        )

    routes = load_json(ROUTES_JSON)
    airports: set[str] = set()

    for route in routes:
        origin = route.get("origin", {}).get("iata")
        destination = route.get("destination", {}).get("iata")

        if origin:
            airports.add(origin)
        if destination:
            airports.add(destination)

    return airports


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


def collect_fr24_airports_seen_in_payload(merged: dict[str, Any]) -> set[str]:
    airports: set[str] = set()

    for selected_iata, selected_data in merged.items():
        airports.add(selected_iata)

        if not isinstance(selected_data, dict):
            continue

        airports |= collect_fr24_airports_from_direction(selected_data.get("arrivals", {}))
        airports |= collect_fr24_airports_from_direction(selected_data.get("departures", {}))

    return airports


def has_fr24_flight_data(value: Any) -> bool:
    """Return true only if the selected airport payload has usable FR24 data."""
    if not isinstance(value, dict):
        return False

    arrivals = value.get("arrivals", {})
    departures = value.get("departures", {})

    return bool(collect_fr24_airports_from_direction(arrivals)) or bool(
        collect_fr24_airports_from_direction(departures)
    )


def main() -> None:
    easyjet_source_airports = collect_easyjet_source_airports()

    merged: dict[str, Any] = {}
    duplicates: list[str] = []
    missing_files: list[Path] = []
    malformed_entries: list[str] = []

    for file in PART_FILES:
        if not file.exists():
            missing_files.append(file)
            continue

        print(f"Loading {file.name}...")

        raw_data = load_json(file)
        data = normalize_fr24_file_payload(raw_data)

        if not isinstance(data, dict):
            raise ValueError(f"{file.name} does not contain a JSON object")

        for airport_iata, airport_data in data.items():
            if not isinstance(airport_iata, str):
                continue

            airport_iata = airport_iata.upper()

            if airport_iata in merged:
                duplicates.append(airport_iata)

            if not isinstance(airport_data, dict):
                malformed_entries.append(
                    f"{file.name}:{airport_iata} -> {type(airport_data).__name__}"
                )

            merged[airport_iata] = airport_data

    fr24_airports_seen = collect_fr24_airports_seen_in_payload(merged)
    fr24_extra_airports = sorted(fr24_airports_seen - easyjet_source_airports)

    easyjet_airports_without_fr24_data = sorted(
        airport
        for airport in easyjet_source_airports
        if not has_fr24_flight_data(merged.get(airport))
    )

    all_airports_for_app = sorted(easyjet_source_airports | set(fr24_extra_airports))

    output = {
        "airports": merged,
        "coverage": {
            "easyjet_source_airports": sorted(easyjet_source_airports),
            "fr24_airports_seen": sorted(fr24_airports_seen),
            "fr24_extra_airports": fr24_extra_airports,
            "easyjet_airports_without_fr24_data": easyjet_airports_without_fr24_data,
            "all_airports_for_app": all_airports_for_app,
        },
    }

    coverage_report = {
        "easyjet_source_airports_count": len(easyjet_source_airports),
        "fr24_selected_airports_count": len(merged),
        "fr24_airports_seen_count": len(fr24_airports_seen),
        "fr24_extra_airports_count": len(fr24_extra_airports),
        "fr24_extra_airports": fr24_extra_airports,
        "easyjet_airports_without_fr24_data_count": len(easyjet_airports_without_fr24_data),
        "easyjet_airports_without_fr24_data": easyjet_airports_without_fr24_data,
        "all_airports_for_app_count": len(all_airports_for_app),
        "malformed_entries_count": len(malformed_entries),
        "malformed_entries": malformed_entries,
        "duplicates_count": len(set(duplicates)),
        "duplicates": sorted(set(duplicates)),
        "missing_files": [str(path) for path in missing_files],
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    with open(COVERAGE_REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(coverage_report, f, ensure_ascii=False, indent=2)

    print()
    print(f"Merged selected FR24 airports: {len(merged)}")
    print(f"FR24 airports seen in payloads: {len(fr24_airports_seen)}")
    print(f"easyJet source airports: {len(easyjet_source_airports)}")
    print(f"Extra FR24 airports: {len(fr24_extra_airports)}")
    print(fr24_extra_airports)
    print(f"easyJet airports without FR24 data: {len(easyjet_airports_without_fr24_data)}")
    print(easyjet_airports_without_fr24_data)
    print()
    print(f"Output: {OUTPUT_FILE}")
    print(f"Coverage report: {COVERAGE_REPORT_FILE}")

    if malformed_entries:
        print()
        print(f"Malformed entries kept but flagged: {len(malformed_entries)}")
        for entry in malformed_entries[:20]:
            print(f"- {entry}")
        if len(malformed_entries) > 20:
            print(f"... and {len(malformed_entries) - 20} more")

    if duplicates:
        print()
        print(f"Duplicate airport keys overwritten: {len(set(duplicates))}")
        print(sorted(set(duplicates)))

    if missing_files:
        print()
        print("Missing files:")
        for path in missing_files:
            print(f"- {path}")


if __name__ == "__main__":
    main()