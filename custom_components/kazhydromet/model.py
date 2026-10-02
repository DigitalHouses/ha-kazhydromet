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


@dataclass(frozen=True)
class ForecastPoint:
    """One native three-hour forecast time slot."""

    at: datetime
    temperature: float
    precipitation: float | None
    humidity: float | None
    pressure: float | None
    wind_speed: float | None
    cloud_coverage: int | None


@dataclass(frozen=True)
class ForecastData:
    """WRF model location and one verified run."""

    station: Station
    generated_at: datetime
    points: tuple[ForecastPoint, ...]

    def current(self, now: datetime) -> ForecastPoint | None:
        """Latest modeled time step no older than one model interval."""
        previous = [p for p in self.points if p.at <= now]
        point = previous[-1] if previous else None
        if point is not None and now - point.at < timedelta(hours=3, minutes=15):
            return point
        return None


def parse_wrf(
    payload: dict, latitude: float, longitude: float, now: datetime
) -> ForecastData:
    """Validate official Kazhydromet WRF JSON and select nearest model point."""
    if not isinstance(payload, dict):
        raise DataContractError("WRF payload is not a JSON object")
    meta = payload.get("meta")
    stations = payload.get("stations")
    forecast_map = payload.get("forecasts")
    if (
        not isinstance(meta, dict)
        or not isinstance(stations, list)
        or not isinstance(forecast_map, dict)
    ):
        raise DataContractError("WRF meta/stations/forecasts contract failed")

    expected_units = {
        "temp_blend": "C",
        "wind_speed": "m/s",
        "precip_mm": "mm",
        "pressure_hpa": "hPa",
        "humidity_rel": "%",
        "cloud_fraction": "0-1",
    }
    units = meta.get("units")
    if (
        not isinstance(units, dict)
        or any(units.get(key) != unit for key, unit in expected_units.items())
        or meta.get("timestep_hours") != 3
    ):
        raise DataContractError("WRF time step or measurement units changed")
    generated = timestamp(meta.get("generated_at"))
    if not now - timedelta(hours=36) <= generated <= now + timedelta(minutes=20):
        raise DataContractError("WRF run is stale or future-dated")

    valid_stations: list[Station] = []
    for item in stations:
        if not isinstance(item, dict):
            continue
        identifier = item.get("rep_id")
        name = item.get("name")
        lat = numeric(item.get("lat"))
        lon = numeric(item.get("lon"))
        if (
            (not isinstance(identifier, (int, str)))
            or isinstance(identifier, bool)
            or not isinstance(name, str)
            or not name
            or lat is None
            or lon is None
            or not -90 <= lat <= 90
            or not -180 <= lon <= 180
        ):
            continue
        if str(identifier) in forecast_map:
            valid_stations.append(Station(str(identifier), name, lat, lon))
    if not valid_stations:
        raise DataContractError("WRF has no valid forecast station coordinates")
    selected = min(valid_stations, key=lambda s: distance_km(s, latitude, longitude))
    raw_points = forecast_map[selected.identifier]
    if not isinstance(raw_points, list):
        raise DataContractError("WRF forecast station is not a time series")

    points: list[ForecastPoint] = []
    for row in raw_points:
        if not isinstance(row, dict):
            raise DataContractError("Invalid WRF time series row")
        at = timestamp(row.get("datetime"))
        temp = numeric(row.get("temp_blend"))
        if temp is None:
            raise DataContractError("WRF time series missing temp_blend")
        cloud = numeric(row.get("cloud_fraction"))
        if cloud is not None and not 0 <= cloud <= 1:
            raise DataContractError("Invalid WRF cloud_fraction")
        humidity = numeric(row.get("humidity_rel"))
        if humidity is not None and not 0 <= humidity <= 100:
            raise DataContractError("Invalid WRF humidity_rel")
        precipitation = numeric(row.get("precip_mm"))
        if precipitation is not None and precipitation < 0:
            raise DataContractError("Invalid WRF precip_mm")
        points.append(
            ForecastPoint(
                at=at,
                temperature=temp,
                precipitation=precipitation,
                humidity=humidity,
                pressure=numeric(row.get("pressure_hpa")),
                wind_speed=numeric(row.get("wind_speed")),
                cloud_coverage=round(cloud * 100) if cloud is not None else None,
            )
        )
    if len(points) < 2 or any(
        b.at - a.at != timedelta(hours=3) for a, b in zip(points, points[1:])
    ):
        raise DataContractError("WRF time series must have contiguous 3-hour slots")
    if points[0].at > now or points[-1].at <= now:
        raise DataContractError("WRF forecast has no coverage for current time")
    return ForecastData(selected, generated, tuple(points))
