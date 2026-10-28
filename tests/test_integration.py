"""The Gotthard's entities."""

import datetime
from http import HTTPStatus

import pytest
from homeassistant.components.camera import async_get_image
from homeassistant.config_entries import SOURCE_REAUTH, ConfigEntryState
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE

from custom_components.gotthard.const import (
    CONF_COUNTERS,
    CONF_COUNTERS_API_KEY,
    NORTH,
    SOUTH,
    UPDATE_INTERVAL,
    WEBCAMS,
)
from custom_components.gotthard.datex import URL

NOW = "2026-10-28T12:00:00+01:00"


@pytest.fixture
async def loaded(hass, entry, feed, freezer):
    freezer.move_to(NOW)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


async def test_queues(hass, loaded):
    def state(name):
        return hass.states.get(f"sensor.gotthard_{name}_before_the_{portal}").state

    portal = "north_portal"
    assert (state("queue"), state("delay")) == ("7.5", "40")
    # The south's message gives no length.
    portal = "south_portal"
    assert (state("queue"), state("delay")) == ("unknown", "15")


async def test_tunnel_and_closures(hass, loaded):
    assert hass.states.get("binary_sensor.gotthard_tunnel").state == STATE_ON
    closure = hass.states.get("sensor.gotthard_next_tunnel_closure")
    assert datetime.datetime.fromisoformat(
        closure.state
    ) == datetime.datetime.fromisoformat("2026-10-28T23:00:00+01:00")
    assert len(closure.attributes["closures"]) == 2


async def test_messages(hass, loaded):
    messages = hass.states.get("sensor.gotthard_traffic_messages")
    assert messages.state == "5"
    assert messages.attributes["messages"][0]["text"].startswith(
        "Freigegeben: A2 Luzern -> Gotthard"
    )
    assert messages.attributes["attribution"].startswith("Data: FEDRO")


async def test_unavailable_when_the_feed_fails(hass, loaded, aioclient_mock, freezer):
    aioclient_mock.clear_requests()
    aioclient_mock.post(URL, status=HTTPStatus.BAD_GATEWAY)
    freezer.tick(UPDATE_INTERVAL)
    await loaded.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.gotthard_tunnel").state == STATE_UNAVAILABLE


async def test_refused_key_asks_for_a_new_one(hass, entry, aioclient_mock):
    aioclient_mock.post(URL, status=HTTPStatus.FORBIDDEN)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == [SOURCE_REAUTH]


async def test_webcams(hass, loaded, aioclient_mock):
    aioclient_mock.get(
        WEBCAMS[NORTH],
        content=b"north",
        headers={"Content-Type": "image/jpeg", "Last-Modified": "then"},
    )
    aioclient_mock.get(WEBCAMS[SOUTH], content=b"south")
    north = await async_get_image(hass, "camera.gotthard_north_portal_goschenen")
    south = await async_get_image(hass, "camera.gotthard_south_portal_airolo")
    assert (north.content, south.content) == (b"north", b"south")
    # Not fetched again so soon.
    await async_get_image(hass, "camera.gotthard_north_portal_goschenen")
    assert (
        sum(str(call[1]) == WEBCAMS[NORTH] for call in aioclient_mock.mock_calls) == 1
    )


async def test_national_roads(hass, loaded):
    axen = hass.states.get("binary_sensor.national_roads_axenstrasse")
    assert axen.state == STATE_OFF
    assert axen.attributes["closures"][0]["text"].startswith(
        "Freigegeben: A4 Altdorf <-> Brunnen zwischen Ortschaft Flüelen"
    )
    nxt = hass.states.get("sensor.national_roads_next_axenstrasse_closure")
    assert datetime.datetime.fromisoformat(
        nxt.state
    ) == datetime.datetime.fromisoformat("2026-11-02T22:00:00+01:00")
    a4 = hass.states.get("sensor.national_roads_a4_closures_northbound_to_schaffhausen")
    assert a4.state == "1"
    assert len(a4.attributes["planned"]) == 2
    a2 = hass.states.get("sensor.national_roads_a2_closures_southbound_to_chiasso")
    assert (a2.state, len(a2.attributes["planned"])) == ("0", 4)


# ── the traffic counters ────────────────────────────────────────────────────
GOSCHENEN = "sensor.a2_goschenen_southbound"


async def test_no_traffic_unless_turned_on(hass, loaded):
    assert hass.states.get(f"{GOSCHENEN}_traffic") is None
    assert hass.states.get("binary_sensor.national_roads_axenstrasse_traffic") is None


@pytest.fixture
async def with_traffic(hass, entry, feed, counters, freezer):
    freezer.move_to(NOW)
    hass.config_entries.async_update_entry(
        entry, options={CONF_COUNTERS: True, CONF_COUNTERS_API_KEY: "counters-key"}
    )
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_station_entities(hass, with_traffic):
    assert hass.states.get(f"{GOSCHENEN}_traffic").state == "600.0"
    assert hass.states.get(f"{GOSCHENEN}_lorries").state == "60.0"
    speed = hass.states.get(f"{GOSCHENEN}_speed")
    assert float(speed.state) == pytest.approx(69.74)
    # On the map.
    assert (speed.attributes["latitude"], speed.attributes["longitude"]) == (
        46.67,
        8.59,
    )
    assert (
        hass.states.get("sensor.a4_sisikon_axenstrasse_northbound_traffic").state
        == "780.0"
    )


async def test_traffic_derived(hass, with_traffic):
    assert (
        hass.states.get(
            "binary_sensor.gotthard_queue_forming_before_the_north_portal"
        ).state
        == STATE_OFF
    )
    assert (
        hass.states.get(
            "binary_sensor.gotthard_queue_forming_before_the_south_portal"
        ).state
        == STATE_OFF
    )
    assert (
        hass.states.get("binary_sensor.national_roads_axenstrasse_traffic").state
        == STATE_ON
    )
    travel = hass.states.get("sensor.national_roads_travel_time_altdorf_goschenen")
    assert 10 < float(travel.state) < 25


async def test_calendars(hass, loaded):
    axen = hass.states.get("calendar.national_roads_axenstrasse")
    # The closure with no end was on its first day only: next are the nights.
    assert axen.state == STATE_OFF
    assert axen.attributes["friendly_name"] == "National roads Axenstrasse (A4)"
    assert (
        axen.attributes["message"]
        == "Axenstrasse (A4) closed: Flüelen-Tunnel – Sisikon"
    )
    result = await hass.services.async_call(
        "calendar",
        "get_events",
        {"entity_id": "calendar.national_roads_axenstrasse", "duration": {"days": 14}},
        blocking=True,
        return_response=True,
    )
    summaries = [
        e["summary"] for e in result["calendar.national_roads_axenstrasse"]["events"]
    ]
    assert summaries.count("Axenstrasse (A4) closed: Flüelen-Tunnel – Sisikon") == 2
    assert hass.states.get("calendar.gotthard_tunnel_closures") is not None
    for key in ("gotthard_pass", "a2", "a4"):
        assert hass.states.get(f"calendar.national_roads_{key}") is not None


async def test_axenstrasse_named_with_its_road_ids_unchanged(hass, loaded):
    """Named "Axenstrasse (A4)"; ids as before, which dashboards use."""
    for entity, name in (
        ("binary_sensor.national_roads_axenstrasse", "National roads Axenstrasse (A4)"),
        (
            "sensor.national_roads_next_axenstrasse_closure",
            "National roads Next Axenstrasse (A4) closure",
        ),
    ):
        assert hass.states.get(entity).attributes["friendly_name"] == name
