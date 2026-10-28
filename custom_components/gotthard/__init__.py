"""Lifecycle of Gotthard."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from custom_components.gotthard.const import CONF_API_KEY, DOMAIN, NAME, UPDATE_INTERVAL
from custom_components.gotthard.datex import (
    AuthError,
    Datex,
    DatexError,
    GotthardStatus,
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.BINARY_SENSOR, Platform.CAMERA, Platform.SENSOR]

type GotthardConfigEntry = ConfigEntry[GotthardCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: GotthardConfigEntry) -> bool:
    coordinator = GotthardCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GotthardConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


class GotthardCoordinator(DataUpdateCoordinator[GotthardStatus]):
    """Pulls the traffic messages, for all the entities."""

    config_entry: GotthardConfigEntry

    def __init__(self, hass: HomeAssistant, entry: GotthardConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.datex = Datex(async_get_clientsession(hass), entry.data[CONF_API_KEY])
        self.device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=NAME,
            manufacturer="FEDRO (ASTRA)",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://www.astra.admin.ch",
        )
        # The A2 and A4 closures and the Axenstrasse, from the same messages.
        self.roads_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{entry.entry_id}-roads")},
            name="National roads",
            manufacturer="FEDRO (ASTRA)",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://www.astra.admin.ch",
        )

    async def _async_update_data(self) -> GotthardStatus:
        try:
            return await self.datex.async_get_status()
        except AuthError as err:
            # Keys expire after six months unless extended.
            raise ConfigEntryAuthFailed(str(err)) from err
        except DatexError as err:
            raise UpdateFailed(str(err)) from err
