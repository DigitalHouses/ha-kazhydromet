"""Native Home Assistant WeatherEntity for observed weather."""

from homeassistant.components.weather import WeatherEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfLength, UnitOfPressure, UnitOfSpeed, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import KazhydrometCoordinator
from .model import condition


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Register the native weather entity."""
    async_add_entities([KazhydrometWeather(hass.data[DOMAIN][entry.entry_id], entry)])


class KazhydrometWeather(CoordinatorEntity[KazhydrometCoordinator], WeatherEntity):
    """Current weather from a timestamp-validated SYNOP observation."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_native_pressure_unit = UnitOfPressure.HPA
    _attr_native_wind_speed_unit = UnitOfSpeed.METERS_PER_SECOND
    _attr_native_visibility_unit = UnitOfLength.KILOMETERS
    _attr_native_precipitation_unit = UnitOfLength.MILLIMETERS

    def __init__(self, coordinator: KazhydrometCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_weather"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Kazhydromet",
            "manufacturer": "Kazhydromet",
        }

    @property
    def native_temperature(self) -> float:
        return self.coordinator.data.temperature

    @property
    def humidity(self) -> float | None:
        return self.coordinator.data.humidity

    @property
    def native_pressure(self) -> float | None:
        return self.coordinator.data.pressure

    @property
    def native_wind_speed(self) -> float | None:
        return self.coordinator.data.wind_speed

    @property
    def wind_bearing(self) -> float | None:
        return self.coordinator.data.wind_direction

    @property
    def native_visibility(self) -> float | None:
        value = self.coordinator.data.visibility
        return value / 1000 if value is not None else None

    @property
    def cloud_coverage(self) -> int | None:
        value = self.coordinator.data.cloud_coverage
        return round(value) if value is not None and 0 <= value <= 100 else None

    @property
    def condition(self) -> str | None:
        sun = self.hass.states.get("sun.sun")
        nighttime = sun is not None and sun.state == "below_horizon"
        current = self.coordinator.data
        return condition(current.description, current.cloud_coverage, nighttime)
