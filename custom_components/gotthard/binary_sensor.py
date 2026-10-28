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

from custom_components.gotthard import (
    CountersCoordinator,
    GotthardConfigEntry,
    GotthardCoordinator,
)
from custom_components.gotthard.const import ATTRIBUTION, NORTH, SOUTH
from custom_components.gotthard.counters import Traffic
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
    if counters := coordinator.counters:
        async_add_entities(
            [
                # A southbound queue is before the north portal.
                TrafficBinary(
                    counters,
                    "queue_forming_north",
                    lambda t: t.forming[SOUTH],
                    coordinator.device_info,
                ),
                TrafficBinary(
                    counters,
                    "queue_forming_south",
                    lambda t: t.forming[NORTH],
                    coordinator.device_info,
                ),
                TrafficBinary(
                    counters,
                    "axenstrasse_traffic",
                    lambda t: t.axen_flowing,
                    coordinator.roads_device_info,
                    BinarySensorDeviceClass.MOVING,
                ),
            ]
        )


class TrafficBinary(CoordinatorEntity[CountersCoordinator], BinarySensorEntity):
    """From the counted traffic: a queue forming, traffic on a road."""

    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: CountersCoordinator,
        key: str,
        value: Callable[[Traffic], bool | None],
        device_info,
        device_class: BinarySensorDeviceClass | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._value = value
        self._attr_translation_key = key
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}-{key}"
        self._attr_device_info = device_info
        self._attr_device_class = device_class

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self._value(self.coordinator.data)


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
