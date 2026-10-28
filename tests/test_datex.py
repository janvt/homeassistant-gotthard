"""Reading the Gotthard's traffic from the feed."""

import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from custom_components.gotthard.const import NORTH, SOUTH
from custom_components.gotthard.datex import DatexError, Queue, parse

FIXTURE = (Path(__file__).parent / "fixtures" / "situations.xml").read_bytes()
CET = datetime.timezone(datetime.timedelta(hours=1))
NOW = datetime.datetime(2026, 10, 28, 12, 0, tzinfo=CET)


def ids(messages):
    """The records' ids, of messages or of closures."""
    return [getattr(m, "message", m).identifier for m in messages]


def local(*args):
    return datetime.datetime(*args, tzinfo=ZoneInfo("Europe/Zurich"))


def test_publication_time():
    status = parse(FIXTURE, NOW)
    assert status.publication_time == datetime.datetime(
        2026, 10, 28, 11, 58, tzinfo=CET
    )


def test_queues_take_the_worst_figures_of_each_portal():
    status = parse(FIXTURE, NOW)
    assert status.queues == {
        NORTH: Queue(length_km=7.5, delay_min=40),
        SOUTH: Queue(length_km=None, delay_min=15),
    }


def test_a_queue_by_its_type_alone():
    status = parse(FIXTURE.replace(b"Sachlage: Stau", b"Sachlage: Unfall"), NOW)
    assert status.queues[NORTH] == Queue(length_km=7.5, delay_min=40)


def test_no_queue():
    document = (
        FIXTURE.replace(b"Sachlage: Stau", b"Sachlage: Unfall")
        .replace(b"stationaryTraffic", b"other")
        .replace(b"queuingTraffic", b"other")
    )
    assert parse(document, NOW).queues == {NORTH: None, SOUTH: None}


def test_messages_are_the_current_ones_about_the_gotthard():
    status = parse(FIXTURE, NOW)
    assert ids(status.messages) == [
        "north-queue",
        "north-queue-longer",
        "south-queue",
        "tunnel-works",
        "pass-closed",
    ]


def test_languages_of_a_text_are_apart():
    message = parse(FIXTURE, NOW).messages[0]
    assert message.text.startswith("Freigegeben: A2 Luzern")
    assert message.text.endswith("[min] 40")
    assert message.in_language("fr").startswith("Libéré: A2 Lucerne")
    assert message.in_language("it").startswith("Approvato: A2 Luzern")
    assert message.in_language("en") == message.text


def test_languages_given_apart():
    tunnel_works = parse(FIXTURE, NOW).messages[3]
    assert tunnel_works.in_language("it").startswith("Approvato: A2 Chiasso")


def test_active_messages_only_from_their_start():
    later = datetime.datetime(2026, 11, 2, 9, 0, tzinfo=CET)
    assert "andermatt-roadworks" not in ids(parse(FIXTURE, NOW).messages)
    assert "andermatt-roadworks" in ids(parse(FIXTURE, later).messages)


def test_the_pass_closed_at_night():
    evening = NOW.replace(hour=19)
    status = parse(FIXTURE, evening)
    closure = status.messages[ids(status.messages).index("pass-night-closure")]
    assert closure.situation == "Strecke gesperrt"
    assert "jusqu'à" in closure.in_language("fr")
    assert not status.tunnel_closed


def test_planned_closures_the_next_first():
    status = parse(FIXTURE, NOW)
    assert not status.tunnel_closed
    assert ids(status.planned_closures) == ["closure-later", "closure-much-later"]
    assert status.planned_closures[1].start == datetime.datetime(
        2026, 11, 2, 20, 0, tzinfo=CET
    )


def test_tunnel_closed_during_a_closure():
    status = parse(FIXTURE, NOW.replace(hour=23, minute=30))
    assert status.tunnel_closed
    assert ids(status.planned_closures) == ["closure-much-later"]


def test_the_pass_closed_is_not_the_tunnel():
    status = parse(FIXTURE, NOW)
    assert "pass-closed" in ids(status.messages)
    assert not status.tunnel_closed


def test_bare_publication_without_envelope():
    start = FIXTURE.index(b"<d2LogicalModel")
    end = FIXTURE.index(b"</d2LogicalModel>") + len(b"</d2LogicalModel>")
    assert parse(FIXTURE[start:end], NOW).queues[NORTH] is not None


@pytest.mark.parametrize("document", [b"not xml", b"<soap:Envelope/>", b"<a/>"])
def test_invalid(document):
    with pytest.raises(DatexError):
        parse(document, NOW)


# ── closures of the A2 and A4 ───────────────────────────────────────────────
def test_the_axenstrasse_closed_with_no_end():
    status = parse(FIXTURE, NOW)
    assert status.axenstrasse.closed
    assert ids(status.axenstrasse.current) == ["axen-now"]
    assert status.axenstrasse.current[0].end is None


def test_an_announced_closure_starts_with_its_period_not_its_announcement():
    """Taking the announcement as the start closed the road from the day it
    was published."""
    status = parse(
        FIXTURE.replace(b"Technische Probleme", b"x")
        .replace(b'id="axen-now"', b'id="axen-now-gone"')
        .replace(
            b"<overallStartTime>2026-09-09T07:08:00.000000Z</overallStartTime>",
            b"<overallStartTime>2026-09-09T07:08:00.000000Z</overallStartTime>"
            b"<overallEndTime>2026-09-10T07:08:00.000000Z</overallEndTime>",
        ),
        NOW,
    )
    assert not status.axenstrasse.closed
    assert ids(status.axenstrasse.planned) == ["axen-nights"]
    assert status.axenstrasse.planned[0].start == local(2026, 11, 2, 22, 0)


def test_a_nightly_closure_only_at_night():
    status = parse(FIXTURE, local(2026, 11, 3, 2, 0))
    night = next(
        c for c in status.axenstrasse.current if c.message.identifier == "axen-nights"
    )
    assert night.end == local(2026, 11, 3, 5, 0)
    # Between its two nights.
    day = parse(FIXTURE, local(2026, 11, 3, 12, 0)).axenstrasse
    assert "axen-nights" not in ids(day.current)
    assert day.planned[0].start == local(2026, 11, 3, 22, 0)
    assert day.planned[0].end == local(2026, 11, 4, 5, 0)


def test_after_its_last_night():
    status = parse(FIXTURE, local(2026, 11, 4, 12, 0))
    assert "axen-nights" not in ids(
        status.axenstrasse.current + status.axenstrasse.planned
    )


def test_ramps_and_exits_are_not_closures():
    status = parse(FIXTURE, NOW)
    every = [
        c
        for road in status.roads.values()
        for d in road.values()
        for c in d.current + d.planned
    ]
    assert not {"axen-ramps", "a4-exit"} & set(ids(every))


def test_closures_by_road_and_direction():
    roads = parse(FIXTURE, NOW).roads
    # The Gotthard tunnel's closures close the A2 too, both ways.
    tunnel = ["closure-later", "closure-much-later"]
    assert ids(roads["A2"][NORTH].planned) == [
        *tunnel,
        "a2-north",
        "a2-both-ways",
        "a2-hagnau",
    ]
    assert ids(roads["A2"][SOUTH].planned) == [*tunnel, "a2-both-ways", "a2-hagnau"]
    assert (
        ids(roads["A4"][NORTH].current)
        == ids(roads["A4"][SOUTH].current)
        == ["axen-now"]
    )
    assert ids(roads["A4"][NORTH].planned) == ["axen-nights", "a4-north"]
    assert ids(roads["A4"][SOUTH].planned) == ["axen-nights"]


def test_a_rescinded_closure_is_gone():
    status = parse(FIXTURE, NOW)
    assert not status.tunnel_closed
    assert "tunnel-rescinded" not in ids(status.tunnel.current + status.tunnel.planned)
