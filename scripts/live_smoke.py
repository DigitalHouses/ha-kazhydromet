"""Read-only live API smoke test for the pure Kazhydromet data parser."""

from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen

path = Path(__file__).resolve().parents[1] / "custom_components/kazhydromet/model.py"
spec = importlib.util.spec_from_file_location("kazhydromet_model_test", path)
model = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = model
spec.loader.exec_module(model)


def get(url):
    request = Request(url, headers={"User-Agent": "Kazhydromet-HA-live-test/0.1"})
    with urlopen(request, timeout=70) as response:
        return json.load(response)


now = datetime.now(timezone.utc)
base = "https://wis2box.kazhydromet.kz/oapi"
stations_payload = get(f"{base}/collections/stations/items?f=json&limit=500")
stations = model.parse_stations(stations_payload["features"])
almaty = next(station for station in stations if station.identifier == "0-20000-0-36870")
print("Stations:", len(stations), "Selected:", almaty, flush=True)

obs_url = (
    f"{base}/collections/"
    "urn%3Awmo%3Amd%3Akz-kazhydromet%3Acore.surface-based-observations.synop"
    "/items?"
    + urlencode({
        "f": "json",
        "limit": 500,
        "wigos_station_identifier": almaty.identifier,
        "datetime": (
            (now - timedelta(hours=12)).isoformat()
            + "/" + now.isoformat()
        ),
    })
)
obs = get(obs_url)
observation = model.parse_observations(
    obs["features"], almaty, now, timedelta(hours=4)
)
print(
    "WIS2:", obs.get("numberMatched"),
    "reportTime:", observation.observed_at.isoformat(),
    "temperature:", observation.temperature,
    flush=True,
)

url = "https://www.kazhydromet.kz/vc/wrf/ftp2/api/forecast_latest.json"
forecast = model.parse_wrf(get(url), 43.25, 76.95, now)
current = forecast.current(now)
assert current is not None, "WRF missing current model time"
print(
    "WRF:", forecast.station,
    "generated:", forecast.generated_at.isoformat(),
    "steps:", len(forecast.points),
    "current temp:", current.temperature,
    flush=True,
)
