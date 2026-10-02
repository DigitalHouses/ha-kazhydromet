"""Diagnostic sensors for source provenance and freshness."""

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
    """Add optional provenance diagnostics."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        KazhydrometObservedAt(coordinator, entry),
        KazhydrometStation(coordinator, entry),
    ])


class KazhydrometDiagnostic(CoordinatorEntity[KazhydrometCoordinator], SensorEntity):
    """A diagnostic belonging to the weather integration device."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self, coordinator: KazhydrometCoordinator, entry: ConfigEntry, suffix: str
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{suffix}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
        }


class KazhydrometObservedAt(KazhydrometDiagnostic):
    """Source timestamp; not the refresh or reception time."""

    _attr_name = "Observation time"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "observed_at")

    @property
    def native_value(self) -> datetime:
        return self.coordinator.data.observed_at


class KazhydrometStation(KazhydrometDiagnostic):
    """Actual WIGOS station chosen on the most recent successful refresh."""

    _attr_name = "Reporting station"

    def __init__(self, coordinator, entry) -> None:
        super().__init__(coordinator, entry, "station")

    @property
    def native_value(self) -> str:
        return self.coordinator.data.station.name
