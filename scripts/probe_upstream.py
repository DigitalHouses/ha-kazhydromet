"""Print a bounded structural preview of Kazhydromet's public API contracts."""

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SOURCES = {
    "wrf": "https://www.kazhydromet.kz/vc/wrf/ftp2/api/forecast_latest.json",
    "stations": "https://wis2box.kazhydromet.kz/oapi/collections/stations/items?f=json&limit=2",
    "synop_recent": (
        "https://wis2box.kazhydromet.kz/oapi/collections/"
        "urn%3Awmo%3Amd%3Akz-kazhydromet%3Acore.surface-based-observations.synop"
        "/items?" + urlencode({
            "f": "json", "limit": 200,
            "wigos_station_identifier": "0-20000-0-36870",
            "datetime": (
                (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()
                + "/" + datetime.now(timezone.utc).isoformat()
            ),
        })
    ),
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
            if name == "wrf":
                print("META:", json.dumps(data["meta"], ensure_ascii=False)[:6000])
                stations = data["stations"]
                nearby = min(stations, key=lambda x: (x["lat"]-43.25)**2 + (x["lon"]-76.95)**2)
                print("NEAR ALMATY:", json.dumps(nearby, ensure_ascii=False))
                selected = data["forecasts"][str(nearby["rep_id"])]
                print("FIRST ROWS:", json.dumps(selected[:3], ensure_ascii=False))
                print("LAST ROW:", json.dumps(selected[-1], ensure_ascii=False))
            if name == "stations":
                print("STATION PROPERTIES:", json.dumps(data["features"][0].get("properties"), ensure_ascii=False)[:6000])
            if name == "synop_recent":
                print("MATCHES:", data.get("numberMatched"), "ROWS:", data.get("numberReturned"))
                print("OBS FIELDS:", json.dumps([(f["properties"]["name"], f["properties"]["units"], f["properties"]["reportTime"], f["properties"]["value"]) for f in data.get("features", [])], ensure_ascii=False)[:7500])
                if data.get("features"):
                    print("RECENT EXAMPLE:", json.dumps(data["features"][:2], ensure_ascii=False)[:3000])
            print(json.dumps(structure(data), ensure_ascii=False, indent=2)[:12000])
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", flush=True)
