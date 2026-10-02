"""Source and freshness diagnostics for Kazhydromet weather."""

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import KazhydrometCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        KazhydrometDiagnostic(coordinator, entry, "observed_at", "observed"),
        KazhydrometDiagnostic(coordinator, entry, "station", "station"),
        KazhydrometDiagnostic(coordinator, entry, "source", "source"),
        KazhydrometDiagnostic(coordinator, entry, "model_run", "model_run"),
        KazhydrometDiagnostic(coordinator, entry, "forecast_location", "forecast_location"),
    ])


class KazhydrometDiagnostic(CoordinatorEntity[KazhydrometCoordinator], SensorEntity):
    """One diagnostic belonging to the same native HA device."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry, suffix: str, kind: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{suffix}"
        self._attr_translation_key = suffix
        self._attr_device_info = {"identifiers": {(DOMAIN, entry.entry_id)}}
        self.kind = kind
        if kind in ("observed", "model_run"):
            self._attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> datetime | str | None:
        snapshot = self.coordinator.data
        observed = snapshot.observation
        forecast = snapshot.forecast
        if self.kind == "observed":
            return observed.observed_at if observed is not None else None
        if self.kind == "station":
            return observed.station.name if observed is not None else None
        if self.kind == "source":
            return snapshot.source()
        if self.kind == "model_run":
            return forecast.generated_at if forecast is not None else None
        if self.kind == "forecast_location":
            return forecast.station.name if forecast is not None else None
        return None
