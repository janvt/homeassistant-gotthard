"""Whether the Gotthard road tunnel, and the Axenstrasse, are open."""

from collections.abc import Callable
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.gotthard import GotthardConfigEntry, GotthardCoordinator
from custom_components.gotthard.const import ATTRIBUTION
from custom_components.gotthard.datex import Closures, GotthardStatus


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GotthardConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        [
            GotthardOpen(
                coordinator,
                "tunnel",
                lambda status: status.tunnel,
                coordinator.device_info,
            ),
            GotthardOpen(
                coordinator,
                "axenstrasse",
                lambda status: status.axenstrasse,
                coordinator.roads_device_info,
            ),
        ]
    )


class GotthardOpen(CoordinatorEntity[GotthardCoordinator], BinarySensorEntity):
    """On while the road is open: closed for a night, works, an accident."""

    _attr_attribution = ATTRIBUTION
    _attr_device_class = BinarySensorDeviceClass.OPENING
    _attr_has_entity_name = True
    _unrecorded_attributes = frozenset({"closures"})

    def __init__(
        self,
        coordinator: GotthardCoordinator,
        key: str,
        closures: Callable[[GotthardStatus], Closures],
        device_info,
    ) -> None:
        super().__init__(coordinator)
        self._closures = closures
        self._attr_translation_key = key
        # The tunnel's unique id is the one it always had.
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}-{key}"
        self._attr_device_info = device_info

    @property
    def is_on(self) -> bool:
        return not self._closures(self.coordinator.data).closed

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """What closes it now, and until when."""
        language = self.hass.config.language.partition("-")[0]
        return {
            "closures": [
                {
                    "text": closure.message.in_language(language),
                    "until": closure.end.isoformat() if closure.end else None,
                    "direction": closure.direction,
                }
                for closure in self._closures(self.coordinator.data).current
            ]
        }
