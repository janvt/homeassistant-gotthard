"""Tests against the real feed and webcams.

Run with the Home Assistant test plugins off, as they block the network:

    pytest -p no:homeassistant -p no:socket tests_live

The feed's tests need a key: set GOTTHARD_API_KEY.
"""

import datetime
import email.utils
import os

import aiohttp
import pytest

from custom_components.gotthard.const import USER_AGENT, WEBCAMS
from custom_components.gotthard.datex import Datex

API_KEY = os.environ.get("GOTTHARD_API_KEY")
needs_key = pytest.mark.skipif(not API_KEY, reason="GOTTHARD_API_KEY is not set")


@pytest.fixture
async def session():
    # The system's resolver: Home Assistant's pins of aiodns and pycares need not
    # match outside it.
    connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
    async with aiohttp.ClientSession(
        connector=connector, headers={"User-Agent": USER_AGENT}
    ) as session:
        yield session


@pytest.mark.parametrize("portal", WEBCAMS)
async def test_webcam_is_recent(session, portal):
    async with session.get(WEBCAMS[portal]) as response:
        assert response.status == 200
        assert response.content_type == "image/jpeg"
        assert (await response.read()).startswith(b"\xff\xd8")
        modified = email.utils.parsedate_to_datetime(response.headers["Last-Modified"])
    age = datetime.datetime.now(datetime.UTC) - modified
    assert age < datetime.timedelta(minutes=30)


@needs_key
async def test_feed(session):
    status = await Datex(session, API_KEY).async_get_status()
    assert status.publication_time is not None
    age = datetime.datetime.now(datetime.UTC) - status.publication_time
    assert age < datetime.timedelta(minutes=15)
    # Whatever the traffic, there are always roadworks or closures to tell.
    print(*(message.text for message in status.messages), sep="\n")
    print(status.queues, status.tunnel_closed, status.planned_closures, sep="\n")


COUNTERS_API_KEY = os.environ.get("COUNTERS_API_KEY")


@pytest.mark.skipif(not COUNTERS_API_KEY, reason="COUNTERS_API_KEY is not set")
async def test_counters(session):
    """Every station still in the feed, with recent minutes."""
    from custom_components.gotthard.counters import (
        STATIONS,
        Averages,
        Counters,
        traffic,
    )

    readings = await Counters(session, COUNTERS_API_KEY).async_get()
    missing = {(s.key, d) for s in STATIONS for d in s.lanes} - set(readings)
    assert not missing, missing
    newest = max(r.time for r in readings.values())
    assert datetime.datetime.now(datetime.UTC) - newest < datetime.timedelta(minutes=15)
    averages = Averages()
    averages.add(readings)
    t = traffic(averages)
    for (key, direction), r in sorted(t.stations.items()):
        print(key, direction, f"{r.flow:.0f}/h", f"{r.lorries:.0f} lorries", r.speed)
    print(t.forming, t.axen_flowing, t.travel)
