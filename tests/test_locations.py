"""Placing the messages, and keeping the A2's and A4's near the Gotthard."""

import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from custom_components.gotthard.const import NORTH
from custom_components.gotthard.datex import parse
from custom_components.gotthard.locations import distance, place

FIXTURE = (Path(__file__).parent / "fixtures" / "situations.xml").read_bytes()
NOW = datetime.datetime(2026, 10, 28, 12, 0, tzinfo=ZoneInfo("Europe/Zurich"))


def ids(messages):
    return {getattr(m, "message", m).identifier for m in messages}


def test_a_code_the_stations_name():
    """Wassen's, from the counting stations' table."""
    assert place(10458) == pytest.approx((46.71, 8.6), abs=0.03)


def test_a_code_between_two_placed_ones():
    """Faido (10462) isn't in the stations' table; 10461 and 10463 are."""
    assert place(10461) and place(10463)
    faido = place(10462)
    assert faido == pytest.approx(
        tuple((a + b) / 2 for a, b in zip(place(10461), place(10463)))
    )


def test_a_code_far_from_any_placed_one():
    assert place(99999) is None
    assert distance((99999,)) is None


def test_distances_from_the_gotthard():
    """Real codes, from the live feed: the Axenstrasse, Stans, Lugano, Basel."""
    assert distance((27078, 27322)) == pytest.approx(39, abs=2)
    assert distance((10447, 10450)) == pytest.approx(46, abs=2)
    assert distance((10469, 10471)) == pytest.approx(61, abs=2)
    assert distance((27710, 27709)) > 100


def test_no_radius_keeps_all():
    status = parse(FIXTURE, NOW)
    assert {"far-roadworks", "a2-hagnau"} <= ids(status.calendars["A2"])


def test_within_45_km():
    status = parse(FIXTURE, NOW, radius_km=45)
    a2 = ids(status.calendars["A2"])
    # Lugano 61 km, Lucerne 54, Basel 127, Stans-Nord–Hergiswil 46: out.
    assert not {"far-roadworks", "a2-both-ways", "a2-hagnau", "a2-north"} & a2
    assert "a4-north" not in ids(status.calendars["A4"])
    assert not {"a2-north", "a2-both-ways", "a2-hagnau"} & ids(
        status.roads["A2"][NORTH].planned
    )
    assert "a4-north" not in ids(status.roads["A4"][NORTH].planned)


def test_messages_that_cant_be_placed_stay():
    """The tunnel's in the fixture have no codes: hiding them could hide a
    local closure."""
    status = parse(FIXTURE, NOW, radius_km=45)
    assert {"closure-later", "closure-much-later"} <= ids(
        status.roads["A2"][NORTH].planned
    )


def test_the_axenstrasse_stays_whatever_the_radius():
    status = parse(FIXTURE, NOW, radius_km=5)
    assert {"axen-now", "axen-nights"} <= ids(status.calendars["axenstrasse"])
    assert status.axenstrasse.closed
    assert "axen-nights" in ids(status.axenstrasse.planned)


def test_a_wider_radius():
    assert "a2-north" in ids(parse(FIXTURE, NOW, radius_km=50).calendars["A2"])
