"""Closures and restrictions as calendar events."""

import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from custom_components.gotthard.datex import parse
from custom_components.gotthard.road_calendar import events, stretch

FIXTURE = (Path(__file__).parent / "fixtures" / "situations.xml").read_bytes()
ZURICH = ZoneInfo("Europe/Zurich")
NOW = datetime.datetime(2026, 10, 28, 12, 0, tzinfo=ZURICH)
FORTNIGHT = NOW + datetime.timedelta(days=14)


def local(*args):
    return datetime.datetime(*args, tzinfo=ZURICH)


def calendar(key, restrictions=False, now=NOW, end=FORTNIGHT):
    status = parse(FIXTURE, now)
    return events(key, status.calendars[key], now, end, now, restrictions, "en")


def test_a_closure_over_several_nights_is_one_event():
    """22:00 to 05:00 on 2 and 3 November: one event from the first night's
    start to the last's end, its hours in its title. An event a night made
    the month view a stack of overlapping bars."""
    nights = [e for e in calendar("axenstrasse") if e.uid.startswith("axen-nights")]
    assert [(e.start, e.end) for e in nights] == [
        (local(2026, 11, 2, 22, 0), local(2026, 11, 4, 5, 0))
    ]
    assert nights[0].summary == (
        "Axenstrasse (A4) closed nightly 22:00–05:00: Flüelen-Tunnel – Sisikon"
    )
    assert nights[0].description.startswith(
        "Cause: Baustelle\nLength: 7.3 km\nAdvice: eine lokale"
    )


def test_a_closure_without_an_end_is_its_first_day_only():
    """Accidents come without an end, and are often never updated: on the day
    they started only, not every day since (the Axenstrasse's of 9 September)."""
    assert not [e for e in calendar("axenstrasse") if e.uid.startswith("axen-now")]
    since = calendar(
        "axenstrasse", now=local(2026, 9, 9, 12, 0), end=local(2026, 9, 12)
    )
    stale = [e for e in since if e.uid.startswith("axen-now")]
    assert [(e.start, e.end) for e in stale] == [
        (local(2026, 9, 9, 9, 8), local(2026, 9, 10, 0, 0))
    ]
    assert stale[0].summary.endswith("(no end announced)")


def test_each_closure_on_one_calendar():
    """The Axenstrasse's aren't on the A4's too, nor the tunnel's on the A2's:
    a card with all the calendars showed them twice."""
    status = parse(FIXTURE, NOW)
    ids = {
        key: {m.identifier for m in messages}
        for key, messages in status.calendars.items()
    }
    assert not ids["axenstrasse"] & ids["A4"]
    assert not ids["tunnel"] & ids["A2"]
    assert "a4-north" in ids["A4"] and "closure-later" in ids["tunnel"]


def test_restrictions_only_when_turned_on():
    assert not [e for e in calendar("tunnel") if "Baustelle:" in e.summary]
    works = [
        e
        for e in calendar("tunnel", restrictions=True)
        if e.uid.startswith("tunnel-works")
    ]
    assert works and works[0].summary.startswith("Gotthard tunnel: Baustelle")


def test_without_times_the_period_comes_from_the_text():
    """The Lugano roadworks have no times but "Dauer: nachts voraussichtlich
    28.10.2026 21:30 bis 29.10.2026 04:00": one night, not every night."""
    lugano = [
        e
        for e in calendar("A2", restrictions=True)
        if e.uid.startswith("far-roadworks")
    ]
    assert [(e.start, e.end) for e in lugano] == [
        (local(2026, 10, 28, 21, 30), local(2026, 10, 29, 4, 0))
    ]
    assert lugano[0].summary.startswith("A2 northbound (to Basel): Fahrbahnverengung")


def test_directions_and_both_ways():
    a2 = {e.uid.split("-2026")[0]: e.summary for e in calendar("A2")}
    assert a2["a2-north"] == (
        "A2 northbound (to Basel) closed nightly 22:00–05:00: "
        "Stans-Nord – Hergiswil Süd"
    )
    assert a2["a2-both-ways"] == (
        "A2 closed nightly 22:00–05:00: Luzern-Zentrum – Sonnenberg-Tunnel"
    )


def test_the_pass_has_its_own_calendar():
    assert any(
        e.uid.startswith("pass-night-closure") for e in calendar("gotthard_pass")
    )
    assert not any(e.uid.startswith("pass-night-closure") for e in calendar("tunnel"))


def test_only_events_in_the_range_asked():
    later = calendar("axenstrasse", end=local(2026, 11, 3, 12, 0))
    assert [e.start for e in later if e.uid.startswith("axen-nights")] == [
        local(2026, 11, 2, 22, 0)
    ]


def test_nights_across_the_change_to_winter_time():
    """25 October 2026: from 22:00 on the 24th to 05:00 on the 26th, local."""
    from dataclasses import replace

    status = parse(FIXTURE, NOW)
    message = next(
        m for m in status.calendars["axenstrasse"] if m.identifier == "axen-nights"
    )
    message = replace(
        message, start=local(2026, 10, 24, 22, 0), end=local(2026, 10, 26, 5, 0)
    )
    out = events(
        "axenstrasse",
        [message],
        local(2026, 10, 24),
        local(2026, 10, 27),
        local(2026, 10, 24),
        False,
        "en",
    )
    assert [(e.start, e.end) for e in out] == [
        (local(2026, 10, 24, 22, 0), local(2026, 10, 26, 5, 0))
    ]


def test_stretch():
    status = parse(FIXTURE, NOW)
    by_id = {m.identifier: m for m in status.calendars["axenstrasse"]}
    assert stretch(by_id["axen-nights"]) == "Flüelen-Tunnel – Sisikon"


# ── one event, not several ──────────────────────────────────────────────────
def _axen_nights():
    status = parse(FIXTURE, NOW)
    return next(
        m for m in status.calendars["axenstrasse"] if m.identifier == "axen-nights"
    )


def test_one_closure_published_per_stretch_is_one_event():
    """FEDRO publishes the Axenstrasse's night closure twice: the Flüelen
    tunnel, and on from it to Sisikon. Same nights, same kind: one event."""
    from dataclasses import replace

    stretch_message = _axen_nights()
    tunnel = replace(
        stretch_message,
        identifier="axen-tunnel",
        texts={
            "de": stretch_message.text.replace(
                "zwischen Tunnel Flüelen-Tunnel und Ortschaft Sisikon",
                "Tunnel Flüelen-Tunnel",
            )
        },
    )
    out = events(
        "axenstrasse", [tunnel, stretch_message], NOW, FORTNIGHT, NOW, False, "en"
    )
    assert [e.summary for e in out] == [
        "Axenstrasse (A4) closed nightly 22:00–05:00: "
        "Flüelen-Tunnel, Flüelen-Tunnel – Sisikon"
    ]
    assert out[0].uid.startswith("axen-tunnel+axen-nights-")


def test_a_restriction_on_daily_hours_is_one_event():
    """Works for years, "nachts" 07:00–17:00: one event over the period, not
    one in every day of the calendar; the hours in its description."""
    from dataclasses import replace

    works = next(
        m
        for m in parse(FIXTURE, NOW).calendars["tunnel"]
        if m.identifier == "tunnel-works"
    )
    works = replace(
        works,
        start=local(2023, 8, 14, 7, 0),
        end=local(2026, 12, 31, 17, 0),
        texts={
            "de": works.text
            + " Dauer: nachts voraussichtlich 14.08.2023 07:00 bis 31.12.2026 17:00"
        },
    )
    out = events("tunnel", [works], NOW, FORTNIGHT, NOW, True, "en")
    assert [(e.start, e.end) for e in out] == [
        (local(2023, 8, 14, 7, 0), local(2026, 12, 31, 17, 0))
    ]
    assert "Daily: 07:00–17:00" in out[0].description


def test_a_part_ends_at_a_heading_with_its_colon():
    """ "Verkehrsführung: veränderte Verkehrsführung" was cut to "veränderte"."""
    from dataclasses import replace

    works = next(
        m
        for m in parse(FIXTURE, NOW).calendars["tunnel"]
        if m.identifier == "tunnel-works"
    )
    works = replace(
        works,
        texts={
            "de": works.text.replace(
                "Zusatz 1:", "Verkehrsführung: veränderte Verkehrsführung Zusatz 1:"
            )
        },
    )
    out = events("tunnel", [works], NOW, FORTNIGHT, NOW, True, "en")
    assert out[0].summary.startswith("Gotthard tunnel: veränderte Verkehrsführung:")
