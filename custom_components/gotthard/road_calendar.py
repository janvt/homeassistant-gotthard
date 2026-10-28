"""Closures and restrictions as calendar events, made readable.

A message reads e.g.

    Freigegeben: A4 Altdorf <-> Brunnen zwischen Tunnel Flüelen-Tunnel und
    Ortschaft Sisikon Sachlage: Strecke gesperrt Baustelle, Länge [km] 7.3
    Dauer: nachts voraussichtlich 02.11.2026 22:00 bis 04.11.2026 05:00
    Empfehlung: eine lokale Umleitung ist eingerichtet

and becomes one event per night, "Axenstrasse closed: Flüelen-Tunnel – Sisikon",
with the cause, the detour and the whole message in its description.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass

from custom_components.gotthard.const import SOUTH
from custom_components.gotthard.datex import (
    BOTH,
    HEADINGS,
    ROADS,
    SWITZERLAND,
    Message,
    is_closure,
)

# A closure or restriction with no end announced: shown on the day it started
# only, marked so.
NO_END = "no end announced"
# Nightly closures are expanded this far at most, whatever is asked.
HORIZON = datetime.timedelta(days=120)
LABELS = {
    "tunnel": "Gotthard tunnel",
    "axenstrasse": "Axenstrasse (A4)",
    "gotthard_pass": "Gotthard Pass",
    "A2": "A2",
    "A4": "A4",
}
# "Freigegeben: … zwischen Anschluss Wassen und Ortschaft Göschenen": the
# kinds of places the messages name, left out of the short stretch.
PLACE_KINDS = re.compile(
    r"^(?:Autobahndreieck Verzweigung|Kreuzung Abzweigung|Parkplatz Dosierstelle|"
    r"Anschluss|Ortschaft|Tunnel|Parkplatz|Zollstation|Raststätte|Pass|"
    r"Dosierstelle|Verzweigung)\s+"
)
PART = r"\s*(.*?)(?=\s+" + HEADINGS + r"|$)"
CAUSE = re.compile(r"Ursache:" + PART)
GUIDANCE = re.compile(r"Verkehrsführung:" + PART)
ADVICE = re.compile(r"Empfehlung:" + PART)
LENGTH = re.compile(r"Länge \[km\]\s*(\d+(?:[.,]\d+)?)")
# "Dauer: nachts voraussichtlich 28.10.2026 21:30 bis 29.10.2026 04:00", or
# without the end: the period in the text, for messages without their times.
DURATION = re.compile(
    r"Dauer:\s*(?:nachts\s+|tagsüber\s+)?voraussichtlich\s+"
    r"(\d\d)\.(\d\d)\.(\d{4})\s+(\d\d):(\d\d)"
    r"(?:\s+bis\s+(\d\d)\.(\d\d)\.(\d{4})\s+(\d\d):(\d\d))?"
)


def period(
    message: Message,
) -> tuple[datetime.datetime | None, datetime.datetime | None]:
    """The message's times, or else those its text gives."""
    start, end = message.start, message.end
    if (start is None or end is None) and (match := DURATION.search(message.text)):
        d1, m1, y1, h1, n1, d2, m2, y2, h2, n2 = match.groups()
        start = start or datetime.datetime(
            int(y1), int(m1), int(d1), int(h1), int(n1), tzinfo=SWITZERLAND
        )
        if end is None and d2:
            end = datetime.datetime(
                int(y2), int(m2), int(d2), int(h2), int(n2), tzinfo=SWITZERLAND
            )
    return start, end


@dataclass(frozen=True)
class Event:
    start: datetime.datetime
    end: datetime.datetime
    summary: str
    description: str
    location: str
    uid: str


def stretch(message: Message) -> str:
    """ "zwischen Anschluss Wassen und Anschluss Göschenen" → "Wassen – Göschenen"."""
    location = message.location
    if match := re.match(r"zwischen\s+(.+?)\s+und\s+(.+)$", location):
        return " – ".join(PLACE_KINDS.sub("", place) for place in match.groups())
    return PLACE_KINDS.sub("", location)


def direction_label(message: Message) -> str:
    places = ROADS.get(message.road)
    direction = message.direction
    if not places or direction in ("", BOTH):
        return ""
    return f"{direction}bound (to {places[-1] if direction == SOUTH else places[0]})"


def summary(key: str, message: Message) -> str:
    heading = _heading(key, message)
    where = stretch(message)
    text = f"{heading}: {where}" if where else heading
    return f"{text} ({NO_END})" if period(message)[1] is None else text


def _heading(key: str, message: Message) -> str:
    """ "Axenstrasse (A4) closed", "A2 northbound (to Basel): Baustelle"."""
    label = LABELS[key]
    if key in ROADS and (direction := direction_label(message)):
        label = f"{label} {direction}"
    if is_closure(message):
        what = "closed"
        if daily := message.daily:
            # One event over all its nights (or days): its hours say when.
            how = "nightly" if daily[1] <= daily[0] else "daily"
            what = f"closed {how} {daily[0]:%H:%M}–{daily[1]:%H:%M}"
    else:
        # The restriction itself: how traffic is led, or what has happened.
        guidance = GUIDANCE.search(message.text)
        what = (guidance.group(1) if guidance else message.situation).rstrip(", ")
        # "Verkehrsbehinderung Baustelle": the second word says it.
        what = re.sub(r"^Verkehrsbehinderung\s+", "", what) or "Verkehrsbehinderung"
    return f"{label} {what}" if what.startswith("closed") else f"{label}: {what}"


def description(message: Message, language: str) -> str:
    lines = []
    if cause := CAUSE.search(message.text):
        lines.append(f"Cause: {cause.group(1).rstrip(', ')}")
    elif cause := _situation_cause(message):
        lines.append(f"Cause: {cause}")
    if (length := LENGTH.search(message.text)) and is_closure(message):
        lines.append(f"Length: {length.group(1)} km")
    if advice := ADVICE.search(message.text):
        lines.append(f"Advice: {advice.group(1)}")
    if (daily := message.daily) and not is_closure(message):
        # A restriction is one event over its period; its hours are here.
        lines.append(f"Daily: {daily[0]:%H:%M}–{daily[1]:%H:%M}")
    text = re.sub(r"^[^:]+:\s*", "", message.in_language(language))
    return "\n".join([*lines, "", text]).strip()


def _situation_cause(message: Message) -> str:
    """ "Strecke gesperrt Baustelle": what's left of the situation once the
    closure or the "Verkehrsbehinderung" is taken off."""
    rest = re.sub(
        r"^(?:(?:Strecke|Tunnel|Strasse) )?gesperrt\s*|^Verkehrsbehinderung\s*",
        "",
        message.situation,
    )
    return rest.rstrip(", ")


def _midnight_after(moment: datetime.datetime) -> datetime.datetime:
    day = moment.astimezone(SWITZERLAND).date() + datetime.timedelta(days=1)
    return datetime.datetime.combine(day, datetime.time(), SWITZERLAND)


def occurrences(
    message: Message,
    start: datetime.datetime,
    end: datetime.datetime,
    now: datetime.datetime,
) -> list[tuple[datetime.datetime, datetime.datetime]]:
    """When the message applies, if that's between `start` and `end`: one event
    from its first hour to its last. A closure only at night or by day runs
    from its first night's start to its last night's end, its hours in its
    title: an event a night made the month view a stack of overlapping bars.
    A restriction on daily hours is one event over its period too."""
    first, last = period(message)
    # Without a start: from today.
    first = first or now.astimezone(SWITZERLAND).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    daily = message.daily if is_closure(message) else None
    if last is None:
        # No end announced, as for an accident, and often never updated: the
        # day it started only (a night closure, its first night).
        last = _midnight_after(first) + (
            datetime.timedelta(days=1) if daily else datetime.timedelta()
        )
    if daily is None:
        return [(first, last)] if first < end and last > start else []
    windows = _windows(first, last, daily, now)
    if not windows:
        return []
    begin, finish = windows[0][0], windows[-1][1]
    return [(begin, finish)] if begin < end and finish > start else []


def _windows(
    first, last, daily, now
) -> list[tuple[datetime.datetime, datetime.datetime]]:
    """Each night (or day) of a closure's period, up to HORIZON from now."""
    out = []
    day = first.astimezone(SWITZERLAND).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    stop = min(now + HORIZON, last)
    while day < stop:
        window = day.replace(hour=daily[0].hour, minute=daily[0].minute)
        window_end = day.replace(hour=daily[1].hour, minute=daily[1].minute)
        if window_end <= window:
            # A night runs past midnight.
            window_end = (day + datetime.timedelta(days=1)).replace(
                hour=daily[1].hour, minute=daily[1].minute
            )
        window_end = min(window_end, last)
        if window >= first and window < window_end:
            out.append((window, window_end))
        # Days as dates, so a change to summer time keeps the hours.
        day = datetime.datetime.combine(
            day.date() + datetime.timedelta(days=1), datetime.time(), SWITZERLAND
        )
    return out


def events(
    key: str,
    messages: list[Message],
    start: datetime.datetime,
    end: datetime.datetime,
    now: datetime.datetime,
    restrictions: bool,
    language: str,
) -> list[Event]:
    """A calendar's events between `start` and `end`, the first first.

    FEDRO publishes one closure as several messages, one per stretch or
    worksite (the Flüelen tunnel, and on to Sisikon): those at the same times
    and of the same kind are one event, naming every stretch."""
    groups: dict[tuple, list[tuple[Message, datetime.datetime, datetime.datetime]]] = {}
    for message in messages:
        if not (restrictions or is_closure(message)):
            continue
        for s, e in occurrences(message, start, end, now):
            same = (s, e, _heading(key, message), period(message)[1] is None)
            groups.setdefault(same, []).append((message, s, e))
    out = []
    for (s, e, heading, no_end), group in groups.items():
        stretches = list(dict.fromkeys(filter(None, (stretch(m) for m, _, _ in group))))
        text = f"{heading}: {', '.join(stretches)}" if stretches else heading
        out.append(
            Event(
                start=s,
                end=e,
                summary=f"{text} ({NO_END})" if no_end else text,
                description="\n\n".join(
                    dict.fromkeys(description(m, language) for m, _, _ in group)
                ),
                location="; ".join(dict.fromkeys(m.location for m, _, _ in group)),
                uid="+".join(m.identifier for m, _, _ in group) + f"-{s.isoformat()}",
            )
        )
    return sorted(out, key=lambda event: (event.start, event.summary))
