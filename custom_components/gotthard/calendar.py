"""The closures (and, opt in, the restrictions) as calendars: the Gotthard
tunnel, the Axenstrasse, the Gotthard Pass, the A2 and the A4."""

import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from custom_components.gotthard import GotthardConfigEntry, GotthardCoordinator
from custom_components.gotthard.const import ATTRIBUTION, CONF_RESTRICTIONS
from custom_components.gotthard.datex import CALENDARS
from custom_components.gotthard.road_calendar import Event, events

# For the event the calendar's state shows: what's on now, or next.
AHEAD = datetime.timedelta(days=60)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GotthardConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        RoadCalendar(
            coordinator,
            key,
            coordinator.device_info
            if key == "tunnel"
            else coordinator.roads_device_info,
        )
        for key in CALENDARS
    )


class RoadCalendar(CoordinatorEntity[GotthardCoordinator], CalendarEntity):
    _attr_attribution = ATTRIBUTION
    _attr_has_entity_name = True

    def __init__(self, coordinator: GotthardCoordinator, key: str, device_info) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_translation_key = f"calendar_{key.lower()}"
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}-calendar_{key.lower()}"
        )
        self._attr_device_info = device_info

    def _events(self, start: datetime.datetime, end: datetime.datetime) -> list[Event]:
        if self.coordinator.data is None:
            return []
        return events(
            self._key,
            self.coordinator.data.calendars[self._key],
            start,
            end,
            dt_util.now(),
            self.coordinator.config_entry.options.get(CONF_RESTRICTIONS, False),
            self.hass.config.language.partition("-")[0],
        )

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.now()
        upcoming = [e for e in self._events(now, now + AHEAD) if e.end > now]
        return _calendar_event(upcoming[0]) if upcoming else None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime.datetime,
        end_date: datetime.datetime,
    ) -> list[CalendarEvent]:
        return [_calendar_event(e) for e in self._events(start_date, end_date)]


def _calendar_event(event: Event) -> CalendarEvent:
    return CalendarEvent(
        start=event.start,
        end=event.end,
        summary=event.summary,
        description=event.description,
        location=event.location,
        uid=event.uid,
    )
