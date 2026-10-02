"""Print a bounded structural preview of Kazhydromet's public API contracts."""

import json
from urllib.request import Request, urlopen

SOURCES = {
    "wrf": "https://www.kazhydromet.kz/vc/wrf/ftp2/api/forecast_latest.json",
    "stations": "https://wis2box.kazhydromet.kz/oapi/collections/stations/items?f=json&limit=2",
    "synop": (
        "https://wis2box.kazhydromet.kz/oapi/collections/"
        "urn%3Awmo%3Amd%3Akz-kazhydromet%3Acore.surface-based-observations.synop"
        "/items?f=json&limit=2"
    ),
}


def structure(value, depth=0):
    """Show keys, small samples and lengths without printing full payloads."""
    if depth > 5:
        return type(value).__name__
    if isinstance(value, dict):
        names = list(value)
        return {
            "count": len(value),
            "keys": names[:30],
            "examples": {
                name: structure(value[name], depth + 1)
                for name in names[:3]
            },
        }
    if isinstance(value, list):
        return {
            "count": len(value),
            "examples": [structure(item, depth + 1) for item in value[:2]],
        }
    return repr(value)[:180]


for name, url in SOURCES.items():
    print(f"### {name}", flush=True)
    try:
        with urlopen(Request(url, headers={"User-Agent": "Kazhydromet-HA-schema-audit/0.1"}), timeout=40) as response:
            body = response.read(16_000_000)
            print(f"HTTP {response.status}; bytes {len(body)}")
            data = json.loads(body)
            print(json.dumps(structure(data), ensure_ascii=False, indent=2)[:12000])
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", flush=True)
