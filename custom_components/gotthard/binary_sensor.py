"""Whether the Gotthard road tunnel is open."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.gotthard import GotthardConfigEntry, GotthardCoordinator
from custom_components.gotthard.const import ATTRIBUTION


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GotthardConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([GotthardTunnel(entry.runtime_data)])


class GotthardTunnel(CoordinatorEntity[GotthardCoordinator], BinarySensorEntity):
    """On while the tunnel is open: closed for a night, a transport, an accident."""

    _attr_attribution = ATTRIBUTION
    _attr_device_class = BinarySensorDeviceClass.OPENING
    _attr_has_entity_name = True
    _attr_translation_key = "tunnel"

    def __init__(self, coordinator: GotthardCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}-tunnel"
        self._attr_device_info = coordinator.device_info

    @property
    def is_on(self) -> bool:
        return not self.coordinator.data.tunnel_closed
