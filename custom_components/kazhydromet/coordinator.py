"""Refresh and station selection, independent of UI and MQTT."""

import logging

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import APIError, KazhydrometAPI
from .const import AUTO_STATION, UPDATE_INTERVAL
from .model import DataContractError, Observation, Station, distance_km

_LOGGER = logging.getLogger(__name__)


class KazhydrometCoordinator(DataUpdateCoordinator[Observation]):
    """Fetch one complete observation; never publish stale data as current."""

    def __init__(
        self, hass: HomeAssistant, api: KazhydrometAPI, requested_station: str
    ) -> None:
        super().__init__(
            hass, _LOGGER, name="Kazhydromet", update_interval=UPDATE_INTERVAL
        )
        self.api = api
        self.requested_station = requested_station
        self._stations: list[Station] | None = None

    async def _async_update_data(self) -> Observation:
        try:
            if self._stations is None:
                self._stations = await self.api.stations()
            if self.requested_station == AUTO_STATION:
                ranked = sorted(
                    self._stations,
                    key=lambda station: distance_km(
                        station, self.hass.config.latitude, self.hass.config.longitude
                    ),
                )
                candidates = ranked[:8]
            else:
                candidates = [
                    station for station in self._stations
                    if station.identifier == self.requested_station
                ]
            if not candidates:
                raise UpdateFailed("Configured WIGOS station not found")
            for station in candidates:
                try:
                    result = await self.api.observation(station)
                except DataContractError as exc:
                    _LOGGER.debug("Station %s unavailable: %s", station.identifier, exc)
                    continue
                return result
            raise UpdateFailed("No recent observations for selected stations")
        except APIError as exc:
            raise UpdateFailed(str(exc)) from exc
