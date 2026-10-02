"""Native HA weather entity with observed conditions and WRF model forecasts."""

from collections import defaultdict
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from homeassistant.components.weather import WeatherEntity, WeatherEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfLength, UnitOfPressure, UnitOfSpeed, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers import sun as sun_helper

from .const import DOMAIN
from .coordinator import KazhydrometCoordinator
from .model import ForecastPoint, condition


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Register the native weather entity."""
    async_add_entities([KazhydrometWeather(hass.data[DOMAIN][entry.entry_id], entry)])


class KazhydrometWeather(CoordinatorEntity[KazhydrometCoordinator], WeatherEntity):
    """Measured current weather; WRF only when observations are unavailable."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_pressure_unit = UnitOfPressure.HPA
    _attr_native_wind_speed_unit = UnitOfSpeed.METERS_PER_SECOND
    _attr_native_visibility_unit = UnitOfLength.KILOMETERS
    _attr_native_precipitation_unit = UnitOfLength.MILLIMETERS
    _attr_supported_features = (
        WeatherEntityFeature.FORECAST_HOURLY | WeatherEntityFeature.FORECAST_DAILY
    )

    def __init__(self, coordinator: KazhydrometCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_weather"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Kazhydromet",
            "manufacturer": "Kazhydromet",
        }

    @property
    def _model_now(self) -> ForecastPoint | None:
        forecast = self.coordinator.data.forecast
        return forecast.current(datetime.now(timezone.utc)) if forecast is not None else None

    @property
    def native_temperature(self) -> float | None:
        observed = self.coordinator.data.observation
        modeled = self._model_now
        return observed.temperature if observed is not None else (
            modeled.temperature if modeled is not None else None
        )

    @property
    def native_dew_point(self) -> float | None:
        return self.coordinator.data.dew_point

    @property
    def humidity(self) -> float | None:
        observed = self.coordinator.data.observation
        modeled = self._model_now
        return observed.humidity if observed is not None else (
            modeled.humidity if modeled is not None else None
        )

    @property
    def native_pressure(self) -> float | None:
        observed = self.coordinator.data.observation
        modeled = self._model_now
        # WIS2 pressure is sea-level-adjusted, WRF is surface pressure. Use
        # source diagnostics when interpreting pressure across source switches.
        return observed.pressure if observed is not None else (
            modeled.pressure if modeled is not None else None
        )

    @property
    def native_wind_speed(self) -> float | None:
        observed = self.coordinator.data.observation
        modeled = self._model_now
        return observed.wind_speed if observed is not None else (
            modeled.wind_speed if modeled is not None else None
        )

    @property
    def wind_bearing(self) -> float | None:
        observed = self.coordinator.data.observation
        return observed.wind_direction if observed is not None else None

    @property
    def native_visibility(self) -> float | None:
        observed = self.coordinator.data.observation
        value = observed.visibility if observed is not None else None
        return value / 1000 if value is not None else None

    @property
    def cloud_coverage(self) -> int | None:
        observed = self.coordinator.data.observation
        modeled = self._model_now
        value = observed.cloud_coverage if observed is not None else (
            modeled.cloud_coverage if modeled is not None else None
        )
        return round(value) if value is not None and 0 <= value <= 100 else None

    @property
    def condition(self) -> str | None:
        night = not sun_helper.is_up(self.hass)
        observed = self.coordinator.data.observation
        description = observed.description if observed is not None else None
        return condition(description, self.cloud_coverage, night)

    @property
    def available(self) -> bool:
        return super().available and self.native_temperature is not None

    @callback
    def _handle_coordinator_update(self) -> None:
        super()._handle_coordinator_update()
        self.hass.async_create_task(self.async_update_listeners())

    async def async_forecast_hourly(self) -> list[dict]:
        """Expose native 3-hour points through HA's hourly forecast API."""
        forecast = self.coordinator.data.forecast
        if forecast is None:
            return []
        now = datetime.now(timezone.utc)
        result = []
        for point in forecast.points:
            if point.at < now:
                continue
            item = {
                "datetime": point.at.isoformat(),
                "native_temperature": point.temperature,
                "condition": condition(None, point.cloud_coverage, not sun_helper.is_up(self.hass, point.at)),
            }
            optional = {
                "humidity": point.humidity,
                "native_precipitation": point.precipitation,
                "native_pressure": point.pressure,
                "native_wind_speed": point.wind_speed,
                "cloud_coverage": point.cloud_coverage,
            }
            item.update({key: value for key, value in optional.items() if value is not None})
            result.append(item)
        return result

    async def async_forecast_daily(self) -> list[dict]:
        """Aggregate only complete local days; never invent missing hours."""
        forecast = self.coordinator.data.forecast
        if forecast is None:
            return []
        zone = ZoneInfo(self.hass.config.time_zone)
        now = datetime.now(timezone.utc)
        grouped = defaultdict(list)
        for point in forecast.points:
            if point.at >= now:
                grouped[point.at.astimezone(zone).date()].append(point)
        result = []
        for day, points in sorted(grouped.items()):
            # Eight 3-hour slots form one complete local 24-hour calendar day.
            if len(points) != 8:
                continue
            high = max(point.temperature for point in points)
            low = min(point.temperature for point in points)
            midnight = datetime.combine(day, time.min, tzinfo=zone).astimezone(timezone.utc)
            item = {
                "datetime": midnight.isoformat(),
                "native_temperature": high,
                "native_templow": low,
            }
            # Each precipitation value covers a three-hour interval. Only
            # sum when slot boundaries align with local midnight; otherwise
            # a full calendar-day total is not defined without interpolation.
            offset = points[0].at.astimezone(zone).utcoffset()
            if (
                offset is not None
                and offset.total_seconds() % (3 * 3600) == 0
                and all(point.precipitation is not None for point in points)
            ):
                item["native_precipitation"] = round(
                    sum(point.precipitation for point in points), 2
                )
            if all(point.cloud_coverage is not None for point in points):
                mean_clouds = round(sum(point.cloud_coverage for point in points) / 8)
                item["cloud_coverage"] = mean_clouds
                item["condition"] = condition(None, mean_clouds, False)
            result.append(item)
        return result
