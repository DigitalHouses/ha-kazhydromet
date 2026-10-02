"""Native UI setup for selecting a Kazhydromet station."""

import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import APIError, KazhydrometAPI
from .const import AUTO_STATION, CONF_STATION, DOMAIN
from .model import distance_km

_LOGGER = logging.getLogger(__name__)


class KazhydrometFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure a station without HACS-specific runtime dependencies."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        """Select closest active station by default, or choose one manually."""
        try:
            stations = await KazhydrometAPI(
                async_get_clientsession(self.hass)
            ).stations()
        except APIError as exc:
            _LOGGER.warning("Unable to load Kazhydromet stations: %s", exc)
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {vol.Required(CONF_STATION, default=AUTO_STATION): vol.In(
                        {AUTO_STATION: "Automatic (nearest reporting station)"}
                    )}
                ),
                errors={"base": "cannot_connect"},
            )

        ordered = sorted(
            stations,
            key=lambda station: distance_km(
                station, self.hass.config.latitude, self.hass.config.longitude
            ),
        )
        choices = {AUTO_STATION: "Automatic (nearest reporting station)"}
        choices.update({station.identifier: station.name for station in ordered})

        if user_input is not None:
            selected = user_input[CONF_STATION]
            if selected not in choices:
                return self.async_abort(reason="invalid_station")
            await self.async_set_unique_id(f"{DOMAIN}:{selected}")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title="Kazhydromet", data={
                CONF_STATION: selected
            })

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_STATION, default=AUTO_STATION): vol.In(choices)
            }),
        )
