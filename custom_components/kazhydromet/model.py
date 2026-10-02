"""Strict, dependency-free parsing of official WIS2 GeoJSON."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import asin, cos, isfinite, radians, sin, sqrt


class DataContractError(ValueError):
    """Source data is missing, malformed, or stale."""


@dataclass(frozen=True)
class Station:
    """WIGOS station with WGS84 coordinates."""

    identifier: str
    name: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class Observation:
    """One coherent SYNOP report, never assembled from different report times."""

    station: Station
    observed_at: datetime
    temperature: float
    humidity: float | None = None
    pressure: float | None = None
    wind_speed: float | None = None
    wind_direction: float | None = None
    visibility: float | None = None
    cloud_coverage: float | None = None
    description: str | None = None


def numeric(value: object) -> float | None:
    """Accept finite real source measurements including zero, but not booleans."""
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    result = float(value)
    return result if isfinite(result) else None


def timestamp(value: object) -> datetime:
    """Require an unambiguous time-zone-aware source timestamp."""
    if not isinstance(value, str):
        raise DataContractError("Invalid or missing reportTime")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DataContractError("Invalid reportTime") from exc
    if result.tzinfo is None:
        raise DataContractError("reportTime has no time zone")
    return result.astimezone(timezone.utc)


def parse_stations(features: list[dict]) -> list[Station]:
    """Parse official station features. Skip incomplete station metadata."""
    result: dict[str, Station] = {}
    for feature in features:
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties")
        geometry = feature.get("geometry")
        if not isinstance(props, dict) or not isinstance(geometry, dict):
            continue
        coords = geometry.get("coordinates")
        if not isinstance(coords, list) or len(coords) < 2:
            continue
        longitude, latitude = numeric(coords[0]), numeric(coords[1])
        identifier = props.get("wigos_station_identifier") or feature.get("id")
        name = props.get("name")
        if (
            not isinstance(identifier, str)
            or not identifier
            or not isinstance(name, str)
            or not name
            or latitude is None
            or longitude is None
            or not -90 <= latitude <= 90
            or not -180 <= longitude <= 180
        ):
            continue
        result[identifier] = Station(identifier, name, latitude, longitude)
    if not result:
        raise DataContractError("Stations collection has no valid coordinates")
    return list(result.values())


def distance_km(station: Station, latitude: float, longitude: float) -> float:
    """Great-circle distance between location and station."""
    dlat = radians(station.latitude - latitude)
    dlon = radians(station.longitude - longitude)
    a = sin(dlat / 2) ** 2 + (
        cos(radians(latitude)) * cos(radians(station.latitude)) * sin(dlon / 2) ** 2
    )
    return 12742 * asin(min(1, sqrt(a)))


def parse_observations(
    features: list[dict], station: Station, now: datetime, max_age: timedelta
) -> Observation:
    """Select most recent complete temperature report within freshness window."""
    reports: dict[datetime, dict[str, object]] = {}
    for feature in features:
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties")
        if not isinstance(props, dict):
            continue
        if props.get("wigos_station_identifier") != station.identifier:
            continue
        try:
            report_time = timestamp(props.get("reportTime"))
        except DataContractError:
            continue
        if not now - max_age <= report_time <= now + timedelta(minutes=15):
            continue
        name = props.get("name")
        if not isinstance(name, str):
            continue
        record = reports.setdefault(report_time, {})
        measurement = numeric(props.get("value"))
        if measurement is not None:
            record[name] = measurement
        elif name == "present_weather" and isinstance(props.get("description"), str):
            record["description"] = props["description"]

    for report_time, record in sorted(reports.items(), reverse=True):
        temperature = record.get("air_temperature")
        if not isinstance(temperature, float):
            continue
        return Observation(
            station=station,
            observed_at=report_time,
            temperature=temperature,
            humidity=record.get("relative_humidity"),
            pressure=record.get("pressure_reduced_to_mean_sea_level"),
            wind_speed=record.get("wind_speed"),
            wind_direction=record.get("wind_direction"),
            visibility=record.get("horizontal_visibility"),
            cloud_coverage=record.get("cloud_cover_total"),
            description=record.get("description"),
        )
    raise DataContractError(
        f"No complete recent air_temperature report for {station.identifier}"
    )


def condition(description: str | None, cloud: float | None, nighttime: bool) -> str | None:
    """Map explicit present-weather text or measured clouds to HA conditions."""
    if description:
        value = description.upper()
        if "THUNDER" in value:
            return "lightning-rainy" if "RAIN" in value else "lightning"
        if "HAIL" in value:
            return "hail"
        if "SNOW" in value:
            return "snowy"
        if "RAIN" in value or "DRIZZLE" in value:
            return "rainy"
        if "FOG" in value or "MIST" in value:
            return "fog"
    if cloud is None:
        return None
    if not 0 <= cloud <= 100:
        return None
    if cloud >= 80:
        return "cloudy"
    if cloud >= 25:
        return "partlycloudy"
    return "clear-night" if nighttime else "sunny"
