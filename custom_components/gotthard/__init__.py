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

from custom_components.gotthard.const import (
    CONF_API_KEY,
    CONF_COUNTERS,
    CONF_COUNTERS_API_KEY,
    COUNTERS_INTERVAL,
    DOMAIN,
    NAME,
    UPDATE_INTERVAL,
)
from custom_components.gotthard.counters import (
    BY_KEY,
    Averages,
    Counters,
    CountersAuthError,
    CountersError,
    Traffic,
    traffic,
)
from custom_components.gotthard.datex import (
    AuthError,
    Datex,
    DatexError,
    GotthardStatus,
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.CALENDAR,
    Platform.CAMERA,
    Platform.SENSOR,
]

type GotthardConfigEntry = ConfigEntry[GotthardCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: GotthardConfigEntry) -> bool:
    coordinator = GotthardCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    # Opt in, in the options.
    if entry.options.get(CONF_COUNTERS) and (
        api_key := entry.options.get(CONF_COUNTERS_API_KEY)
    ):
        coordinator.counters = CountersCoordinator(hass, entry, api_key)
        # The counts are extra: without them the rest still sets up.
        await coordinator.counters.async_refresh()
    entry.runtime_data = coordinator
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: GotthardConfigEntry
) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


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
        self.counters: CountersCoordinator | None = None
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


class CountersCoordinator(DataUpdateCoordinator[Traffic]):
    """Pulls the traffic counts, and averages them over the last few pulls."""

    config_entry: GotthardConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: GotthardConfigEntry, api_key: str
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_counters",
            update_interval=COUNTERS_INTERVAL,
        )
        self.client = Counters(async_get_clientsession(hass), api_key)
        self.averages = Averages()

    def station_device(self, key: str) -> DeviceInfo:
        station = BY_KEY[key]
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.config_entry.entry_id}-{key}")},
            name=station.name,
            manufacturer="FEDRO (ASTRA)",
            model="Traffic counting station",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def _async_update_data(self) -> Traffic:
        try:
            self.averages.add(await self.client.async_get())
        except CountersAuthError as err:
            # Not a reauth: that is for the traffic messages' key.
            raise UpdateFailed(
                f"{err}: set a new traffic counters key in the options"
            ) from err
        except CountersError as err:
            raise UpdateFailed(str(err)) from err
        return traffic(self.averages)
