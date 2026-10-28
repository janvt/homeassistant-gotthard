"""Queues before the portals, closures and messages of the Gotthard, and the
closures of the A2 and A4."""

import datetime
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfLength, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from custom_components.gotthard import GotthardConfigEntry, GotthardCoordinator
from custom_components.gotthard.const import ATTRIBUTION, NORTH, SOUTH
from custom_components.gotthard.datex import (
    ROADS,
    Closure,
    Closures,
    GotthardStatus,
    Message,
)


@dataclass(frozen=True, kw_only=True)
class GotthardSensorDescription(SensorEntityDescription):
    value: Callable[[GotthardStatus], Any]
    attributes: Callable[[GotthardStatus, str], dict[str, Any]] | None = None
    # The Gotthard's, or the national roads'.
    roads: bool = False


def _length(portal: str) -> Callable[[GotthardStatus], float | None]:
    def value(status: GotthardStatus) -> float | None:
        queue = status.queues[portal]
        # No queue reported is no queue; a queue without a length is unknown.
        return 0 if queue is None else queue.length_km

    return value


def _delay(portal: str) -> Callable[[GotthardStatus], int | None]:
    def value(status: GotthardStatus) -> int | None:
        queue = status.queues[portal]
        return 0 if queue is None else queue.delay_min

    return value


def _next(closures: Callable[[GotthardStatus], Closures]):
    def value(status: GotthardStatus) -> datetime.datetime | None:
        planned = closures(status).planned
        return planned[0].start if planned else None

    return value


def _planned(closures: Callable[[GotthardStatus], Closures]):
    def attributes(status: GotthardStatus, language: str) -> dict[str, Any]:
        return {"closures": [_closure(c, language) for c in closures(status).planned]}

    return attributes


def _road(road: str, direction: str) -> Callable[[GotthardStatus], Closures]:
    return lambda status: status.roads[road][direction]


def _road_attributes(closures: Callable[[GotthardStatus], Closures]):
    def attributes(status: GotthardStatus, language: str) -> dict[str, Any]:
        return {
            "current": [_closure(c, language) for c in closures(status).current],
            "planned": [_closure(c, language) for c in closures(status).planned],
        }

    return attributes


def _message_attributes(status: GotthardStatus, language: str) -> dict[str, Any]:
    return {"messages": [_describe(message, language) for message in status.messages]}


def _describe(message: Message, language: str) -> dict[str, Any]:
    return {
        "text": message.in_language(language),
        "start": message.start.isoformat() if message.start else None,
        "end": message.end.isoformat() if message.end else None,
    }


def _closure(closure: Closure, language: str) -> dict[str, Any]:
    return {
        "text": closure.message.in_language(language),
        "start": closure.start.isoformat() if closure.start else None,
        "end": closure.end.isoformat() if closure.end else None,
        "direction": closure.direction,
    }


def _tunnel(status: GotthardStatus) -> Closures:
    return status.tunnel


def _axenstrasse(status: GotthardStatus) -> Closures:
    return status.axenstrasse


SENSORS = [
    *(
        GotthardSensorDescription(
            key=f"queue_{portal}",
            translation_key=f"queue_{portal}",
            device_class=SensorDeviceClass.DISTANCE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfLength.KILOMETERS,
            suggested_display_precision=1,
            value=_length(portal),
        )
        for portal in (NORTH, SOUTH)
    ),
    *(
        GotthardSensorDescription(
            key=f"delay_{portal}",
            translation_key=f"delay_{portal}",
            device_class=SensorDeviceClass.DURATION,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTime.MINUTES,
            value=_delay(portal),
        )
        for portal in (NORTH, SOUTH)
    ),
    GotthardSensorDescription(
        key="next_closure",
        translation_key="next_closure",
        device_class=SensorDeviceClass.TIMESTAMP,
        value=_next(_tunnel),
        attributes=_planned(_tunnel),
    ),
    GotthardSensorDescription(
        key="messages",
        translation_key="messages",
        state_class=SensorStateClass.MEASUREMENT,
        value=lambda status: len(status.messages),
        attributes=_message_attributes,
    ),
    GotthardSensorDescription(
        key="next_axenstrasse_closure",
        translation_key="next_axenstrasse_closure",
        device_class=SensorDeviceClass.TIMESTAMP,
        value=_next(_axenstrasse),
        attributes=_planned(_axenstrasse),
        roads=True,
    ),
    # How many closures each road has now, by direction; they and those to
    # come in the attributes.
    *(
        GotthardSensorDescription(
            key=f"closures_{road.lower()}_{direction}",
            translation_key=f"closures_{road.lower()}_{direction}",
            value=lambda status, c=_road(road, direction): len(c(status).current),
            attributes=_road_attributes(_road(road, direction)),
            roads=True,
        )
        for road in ROADS
        for direction in (NORTH, SOUTH)
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GotthardConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(
        GotthardSensor(entry.runtime_data, description) for description in SENSORS
    )


class GotthardSensor(CoordinatorEntity[GotthardCoordinator], SensorEntity):
    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True
    # Long lists of texts, which change with every message: not for the
    # recorder.
    _unrecorded_attributes = frozenset({"messages", "closures", "current", "planned"})
    entity_description: GotthardSensorDescription

    def __init__(
        self, coordinator: GotthardCoordinator, description: GotthardSensorDescription
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}-{description.key}"
        self._attr_device_info = (
            coordinator.roads_device_info
            if description.roads
            else coordinator.device_info
        )

    @property
    def native_value(self) -> Any:
        return self.entity_description.value(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attributes is None:
            return None
        language = self.hass.config.language.partition("-")[0]
        return self.entity_description.attributes(self.coordinator.data, language)
