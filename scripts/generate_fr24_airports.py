

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROUTES_JSON = ROOT / "data" / "easyjet_routes_enriched.json"
OUTPUT_JS = ROOT / "data" / "fr24_airports.js"


def main() -> None:
    if not ROUTES_JSON.exists():
        raise FileNotFoundError(
            f"Could not find {ROUTES_JSON}. Run scripts/enrich_routes.py first."
        )

    routes = json.loads(ROUTES_JSON.read_text(encoding="utf-8"))

    airports: set[str] = set()
    for route in routes:
        origin_iata = route.get("origin", {}).get("iata")
        destination_iata = route.get("destination", {}).get("iata")

        if origin_iata:
            airports.add(origin_iata)
        if destination_iata:
            airports.add(destination_iata)

    sorted_airports = sorted(airports)

    js = "const airports = " + json.dumps(sorted_airports, indent=2) + ";\n"
    OUTPUT_JS.parent.mkdir(exist_ok=True)
    OUTPUT_JS.write_text(js, encoding="utf-8")

    print(f"Found {len(sorted_airports)} airports")
    print(f"Wrote {OUTPUT_JS}")
    print()
    print(js)


if __name__ == "__main__":
    main()