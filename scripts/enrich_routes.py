from pathlib import Path
import json
import re
from html import unescape

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "easyroutes_sources.html"
OUTPUT = ROOT / "data" / "easyjet_routes_enriched.json"

def main():
    html = SOURCE.read_text(encoding="utf-8")

    pattern = re.compile(
        r"&lt;strong&gt;</span>([^<]+?)<span class=\"html-tag\">&lt;/strong&gt;</span>\s*to\s*"
        r"<span class=\"html-tag\">&lt;strong&gt;</span>([^<]+?)<span class=\"html-tag\">&lt;/strong&gt;"
    )

    routes = []
    seen = set()

    for origin, destination in pattern.findall(html):
        origin = unescape(origin).strip()
        destination = unescape(destination).strip()

        route_match = re.match(r"(.+?) \(([A-Z]{3})\)", origin)
        dest_match = re.match(r"(.+?) \(([A-Z]{3})\)", destination)

        if not route_match or not dest_match:
            continue

        origin_name, origin_iata = route_match.groups()
        dest_name, dest_iata = dest_match.groups()
        key = f"{origin_iata}-{dest_iata}"

        if key in seen:
            continue
        seen.add(key)

        routes.append({
            "route": key,
            "origin": {"iata": origin_iata, "name": origin_name},
            "destination": {"iata": dest_iata, "name": dest_name},
            "weekly_frequency": None
        })

    routes.sort(key=lambda r: r["route"])

    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(json.dumps(routes, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Wrote {len(routes)} routes to {OUTPUT}")

if __name__ == "__main__":
    main()