"""Forecast parsing for the Kazhydromet WRF JSON contract."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import isfinite
from zoneinfo import ZoneInfo

from .model import DataContractError, condition, distance_km, numeric, Station, timestamp


@dataclass(frozen=True)
class ForecastData:
    """Verified official WRF forecast with native Home Assistant fields."""

    generated_at: datetime
    station_name: str
    hourly: list[dict]
    daily: list[dict]


def _required_number(row: dict, key: str) -> float:
    value = numeric(row.get(key))
    if value is None:
        raise DataContractError(f"WRF forecast missing {key}")
    return value


def _condition_for_row(row: dict, value: float) -> str:
    """Generate a condition only from source cloud cover and precipitation."""
    rain = _required_number(row, "precip_mm")
    if rain > 0:
        return "snowy" if value <= 0 else "rainy"
    cloud = _required_number(row, "cloud_fraction")
    if not 0 <= cloud <= 1:
        raise DataContractError("WRF cloud_fraction not in 0..1")
    return condition(None, cloud * 100, False) or "cloudy"


def parse_wrf(
    payload: dict,
    latitude: float,
    longitude: float,
    timezone_name: str,
    now: datetime,
) -> ForecastData:
    """Validate source generation and select the nearest WRF forecast point."""
    if not isinstance(payload, dict):
        raise DataContractError("WRF forecast must be an object")
    meta = payload.get("meta")
    stations = payload.get("stations")
    forecasts = payload.get("forecasts")
    if not isinstance(meta, dict) or not isinstance(stations, list) or not isinstance(forecasts, dict):
        raise DataContractError("WRF missing required meta, stations or forecasts")
    generated = timestamp(meta.get("generated_at"))
    if generated > now + timedelta(minutes=15) or now - generated > timedelta(hours=36):
        raise DataContractError("WRF forecast is stale or in the future")
    if meta.get("timestep_hours") != 3:
        raise DataContractError("Unexpected WRF forecast timestep")
    units = meta.get("units")
    if not isinstance(units, dict) or any(
        units.get(k) != v for k, v in {
            "temp_blend": "C", "wind_speed": "m/s",
            "precip_mm": "mm", "pressure_hpa": "hPa",
            "humidity_rel": "%", "cloud_fraction": "0-1",
        }.items()
    ):
        raise DataContractError("Unexpected WRF forecast units")
    candidates = []
    for station in stations:
        if not isinstance(station, dict):
            continue
        lat, lon = numeric(station.get("lat")), numeric(station.get("lon"))
        identifier = station.get("rep_id")
        if lat is None or lon is None or identifier is None:
            continue
        key = str(identifier)
        if not -90 <= lat <= 90 or not -180 <= lon <= 180:
            continue
        if isinstance(forecasts.get(key), list):
            candidates.append((
                distance_km(Station(key, key, lat, lon), latitude, longitude),
                key, station,
            ))
    if not candidates:
        raise DataContractError("WRF contains no valid forecast stations")
    _, key, location = min(candidates)
    rows = forecasts[key]
    tz = ZoneInfo(timezone_name)
    hourly: list[dict] = []
    daily_rows: dict[str, list[dict]] = {}
    seen: set[datetime] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise DataContractError("WRF forecast row is not an object")
        at = timestamp(row.get("datetime"))
        if at in seen:
            raise DataContractError("Duplicate WRF forecast timestamp")
        seen.add(at)
        if at < now - timedelta(hours=3):
            continue
        temperature = _required_number(row, "temp_blend")
        cloud = _required_number(row, "cloud_fraction")
        if not 0 <= cloud <= 1:
            raise DataContractError("WRF cloud_fraction not in 0..1")
        precipitation = _required_number(row, "precip_mm")
        if precipitation < 0:
            raise DataContractError("Negative WRF precipitation")
        humidity = _required_number(row, "humidity_rel")
        if not 0 <= humidity <= 100:
            raise DataContractError("WRF humidity out of range")
        entry = {
            "datetime": at.isoformat(),
            "native_temperature": temperature,
            "native_wind_speed": _required_number(row, "wind_speed"),
            "native_pressure": _required_number(row, "pressure_hpa"),
            "native_precipitation": precipitation,
            "humidity": humidity,
            "cloud_coverage": round(cloud * 100),
            "condition": _condition_for_row(row, temperature),
        }
        hourly.append(entry)
        day = at.astimezone(tz).date().isoformat()
        daily_rows.setdefault(day, []).append((at, entry))
    if not hourly:
        raise DataContractError("WRF contains no current or future forecasts")
    daily = []
    for day, samples in sorted(daily_rows.items()):
        # Only complete days may carry precipitation totals. Timestamp at the
        # beginning of each three-hour interval is not the local date midnight.
        numbers = [r["native_temperature"] for _, r in samples]
        peak = max(samples, key=lambda item: item[1]["native_temperature"])[1]
        at = samples[0][0]
        item = {
            "datetime": at.isoformat(),
            "native_temperature": max(numbers),
            "native_templow": min(numbers),
            "condition": peak["condition"],
        }
        if len(samples) == 8:
            item["native_precipitation"] = round(
                sum(r["native_precipitation"] for _, r in samples), 2
            )
        daily.append(item)
    name = location.get("name")
    return ForecastData(
        generated_at=generated,
        station_name=name if isinstance(name, str) and name else key,
        hourly=hourly,
        daily=daily,
    )
