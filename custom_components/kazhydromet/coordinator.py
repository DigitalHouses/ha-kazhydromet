"""Data coordinator for official WIS2 observations and WRF forecasts."""

from dataclasses import dataclass
import logging
from datetime import datetime, timezone

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import APIError, KazhydrometAPI
from .const import AUTO_STATION, UPDATE_INTERVAL, WRF_REFRESH
from .model import (
    DataContractError,
    ForecastData,
    Observation,
    distance_km,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class WeatherSnapshot:
    """Independent observations and forecasts with explicit source provenance."""

    observation: Observation | None
    forecast: ForecastData | None

    def source(self) -> str:
        return "WIS2 observation" if self.observation is not None else "WRF model"


class KazhydrometCoordinator(DataUpdateCoordinator[WeatherSnapshot]):
    """Refresh from both sources without forging measurements on failure."""

    def __init__(
        self, hass: HomeAssistant, api: KazhydrometAPI, requested_station: str
    ) -> None:
        super().__init__(
            hass, _LOGGER, name="Kazhydromet", update_interval=UPDATE_INTERVAL
        )
        self.api = api
        self.requested_station = requested_station
        self._stations = None

    async def _async_update_data(self) -> WeatherSnapshot:
        forecast = None
        try:
            forecast = await self.api.forecast(
                self.hass.config.latitude, self.hass.config.longitude
            )
        except APIError as exc:
            _LOGGER.warning("WRF forecast unavailable: %s", exc)

        observation = None
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
            for station in candidates:
                try:
                    observation = await self.api.observation(station)
                except DataContractError as exc:
                    _LOGGER.debug(
                        "Station %s has no recent SYNOP data: %s", station.identifier, exc
                    )
                    continue
                break
        except APIError as exc:
            _LOGGER.warning("WIS2 observations unavailable: %s", exc)

        if forecast is None and observation is None:
            raise UpdateFailed("Neither WIS2 observations nor WRF forecast is available")
        if observation is None:
            _LOGGER.warning("Using modeled WRF temperature; no fresh WIS2 observation")
        return WeatherSnapshot(observation, forecast)

    async def _refresh_forecast(self) -> None:
        """Refresh WRF only every three hours without blocking observations on errors."""
        now = datetime.now(timezone.utc)
        if (
            self._last_wrf_fetch is not None
            and now - self._last_wrf_fetch < WRF_REFRESH
        ):
            return
        self._last_wrf_fetch = now
        try:
            raw = await self.api.wrf()
            self.forecast = parse_wrf(
                raw, self.hass.config.latitude, self.hass.config.longitude,
                self.hass.config.time_zone, now
            )
        except (APIError, DataContractError) as exc:
            _LOGGER.warning("Kazhydromet WRF forecast unavailable: %s", exc)
            if (
                self.forecast is not None
                and now - self.forecast.generated_at > WRF_REFRESH * 12
            ):
                self.forecast = None
