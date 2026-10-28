"""The webcams before the Gotthard road tunnel's portals."""

import asyncio
import logging
import time

import aiohttp
from homeassistant.components.camera import Camera
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from custom_components.gotthard import GotthardConfigEntry, GotthardCoordinator
from custom_components.gotthard.const import USER_AGENT, WEBCAM_REFRESH, WEBCAMS

_LOGGER = logging.getLogger(__name__)
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GotthardConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(
        GotthardWebcam(entry.runtime_data, portal, url)
        for portal, url in WEBCAMS.items()
    )


class GotthardWebcam(Camera):
    """A still image, fetched again when it may have changed."""

    _attr_has_entity_name = True
    # The images change every 5 minutes; a stream would show the same one.
    _attr_frame_interval = WEBCAM_REFRESH.total_seconds()

    def __init__(self, coordinator: GotthardCoordinator, portal: str, url: str) -> None:
        super().__init__()
        self._url = url
        self._attr_translation_key = f"webcam_{portal}"
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}-webcam_{portal}"
        self._attr_device_info = coordinator.device_info
        self._image: bytes | None = None
        self._last_modified: str | None = None
        self._fetched = 0.0
        self._lock = asyncio.Lock()

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        async with self._lock:
            if time.monotonic() - self._fetched >= WEBCAM_REFRESH.total_seconds():
                await self._async_fetch()
            return self._image

    async def _async_fetch(self) -> None:
        headers = {"User-Agent": USER_AGENT}
        if self._last_modified and self._image:
            headers["If-Modified-Since"] = self._last_modified
        try:
            async with async_get_clientsession(self.hass).get(
                self._url, headers=headers, timeout=REQUEST_TIMEOUT
            ) as response:
                if response.status == 200:
                    self._image = await response.read()
                    self._last_modified = response.headers.get("Last-Modified")
                elif response.status != 304:
                    _LOGGER.debug("HTTP %s from %s", response.status, self._url)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            # The last image is shown until the webcam is back.
            _LOGGER.debug("Cannot fetch %s: %r", self._url, err)
        self._fetched = time.monotonic()
