"""Reading the traffic counts, from a real minute of the feed."""

import datetime
import gzip
from pathlib import Path

import pytest

from custom_components.gotthard.const import NORTH, SOUTH
from custom_components.gotthard.counters import (
    SAMPLES,
    SITES,
    STATIONS,
    Averages,
    CountersError,
    Reading,
    parse,
    traffic,
)

FIXTURE = (Path(__file__).parent / "fixtures" / "measured.xml").read_bytes()
MINUTE = datetime.datetime(2026, 10, 28, 14, 47, tzinfo=datetime.UTC)


def test_every_station_and_direction():
    readings = parse(FIXTURE)
    assert set(readings) == {(s.key, d) for s in STATIONS for d in (NORTH, SOUTH)}


def test_each_site_in_one_station_once():
    """A lane in two stations, or twice, would count its vehicles twice."""
    assert len(SITES) == len(set(SITES))


def test_cars_and_lorries_added_speeds_weighted_by_vehicles():
    """Göschenen southbound: 540 cars at 69.6 km/h (9 of them), 60 lorries
    at 71.0 (1). The feed's own "any vehicle" total reads 0."""
    reading = parse(FIXTURE)[("a2_goschenen", SOUTH)]
    assert (reading.flow, reading.lorries) == (600, 60)
    assert reading.speed == pytest.approx((69.6 * 9 + 71.0) / 10)
    assert reading.time == MINUTE


def test_lanes_added():
    """Gurtnellen has two lanes each way."""
    reading = parse(FIXTURE)[("a2_gurtnellen", SOUTH)]
    assert reading.flow == 1440


def test_gzipped_without_saying_so():
    assert parse(gzip.compress(FIXTURE)) == parse(FIXTURE)


def test_invalid():
    with pytest.raises(CountersError):
        parse(b"not xml")


def test_no_vehicles_no_speed():
    document = FIXTURE.replace(b"<dx223:speed>", b"<dx223:nospeed>").replace(
        b"</dx223:speed>", b"</dx223:nospeed>"
    )
    assert parse(document)[("a2_goschenen", SOUTH)].speed is None


# ── averaging, and what is made of it ───────────────────────────────────────
def minute(at: int, flow: float, speed: float | None, lorries: float = 0) -> Reading:
    return Reading(flow, lorries, speed, MINUTE + datetime.timedelta(minutes=at))


def test_averaged_over_the_last_pulls():
    averages = Averages()
    for at in range(SAMPLES + 2):
        averages.add({("a2_wassen", SOUTH): minute(at, 60 * at, 100)})
    reading = averages.get("a2_wassen", SOUTH)
    # The last SAMPLES minutes only.
    assert reading.flow == sum(60 * at for at in range(2, SAMPLES + 2)) / SAMPLES


def test_a_repeated_minute_counts_once():
    averages = Averages()
    averages.add({("a2_wassen", SOUTH): minute(0, 600, 100)})
    averages.add({("a2_wassen", SOUTH): minute(0, 600, 100)})
    averages.add({("a2_wassen", SOUTH): minute(1, 0, None)})
    assert averages.get("a2_wassen", SOUTH).flow == 300


def test_speed_weighted_by_flow():
    averages = Averages()
    averages.add({("a2_wassen", SOUTH): minute(0, 1200, 20)})
    averages.add({("a2_wassen", SOUTH): minute(1, 60, 120)})
    assert averages.get("a2_wassen", SOUTH).speed == pytest.approx(
        (1200 * 20 + 60 * 120) / 1260
    )


def live() -> Averages:
    averages = Averages()
    averages.add(parse(FIXTURE))
    return averages


def test_the_live_minute():
    t = traffic(live())
    assert t.forming == {SOUTH: False, NORTH: False}
    # 1020 vehicles an hour on the Axenstrasse: open, whatever the feed says.
    assert t.axen_flowing is True
    assert 10 < t.travel["altdorf_goschenen"] < 25


def test_a_queue_forming_southbound():
    averages = live()
    averages.add({("a2_goschenen", SOUTH): minute(5, 600, 8)})
    averages.add({("a2_goschenen", SOUTH): minute(6, 600, 8)})
    averages.add({("a2_goschenen", SOUTH): minute(7, 600, 8)})
    t = traffic(averages)
    assert t.forming == {SOUTH: True, NORTH: False}
    assert t.travel["altdorf_goschenen"] > traffic(live()).travel["altdorf_goschenen"]


def test_nothing_on_the_axenstrasse():
    averages = Averages()
    for at in range(SAMPLES):
        averages.add(
            {
                ("a4_sisikon", SOUTH): minute(at, 0, None),
                ("a4_sisikon", NORTH): minute(at, 0, None),
            }
        )
    assert traffic(averages).axen_flowing is False
    assert traffic(Averages()).axen_flowing is None


def test_a_travel_time_needs_every_stretch():
    averages = live()
    averages.readings.pop(("a2_amsteg", SOUTH))
    averages.readings.pop(("a2_gurtnellen", SOUTH))
    assert traffic(averages).travel["altdorf_goschenen"] is None
