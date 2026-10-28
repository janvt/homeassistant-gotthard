"""Reading the Gotthard's traffic from the feed."""

import datetime
from pathlib import Path

import pytest

from custom_components.gotthard.const import NORTH, SOUTH
from custom_components.gotthard.datex import DatexError, Queue, parse

FIXTURE = (Path(__file__).parent / "fixtures" / "situations.xml").read_bytes()
CET = datetime.timezone(datetime.timedelta(hours=1))
NOW = datetime.datetime(2026, 10, 28, 12, 0, tzinfo=CET)


def ids(messages):
    return [message.identifier for message in messages]


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


def test_messages_in_other_languages():
    message = parse(FIXTURE, NOW).messages[0]
    assert message.in_language("fr").startswith("Libéré: A2 Lucerne")
    assert message.in_language("en") == message.text


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
