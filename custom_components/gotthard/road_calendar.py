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
    ROADS,
    SWITZERLAND,
    Message,
    is_closure,
)

# A closure or restriction with no end announced: shown until the end of each
# day, marked so.
NO_END = "no end announced"
# Nightly closures are expanded this far at most, whatever is asked.
HORIZON = datetime.timedelta(days=120)
LABELS = {
    "tunnel": "Gotthard tunnel",
    "axenstrasse": "Axenstrasse",
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
PART = (
    r"\s*(.*?)(?=\s+(?:Länge|Ursache|Zusatz \d|Dauer|Verkehrsführung|Empfehlung)\b|$)"
)
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
    label = LABELS[key]
    if key in ROADS and (direction := direction_label(message)):
        label = f"{label} {direction}"
    if is_closure(message):
        what = "closed"
    else:
        # The restriction itself: how traffic is led, or what has happened.
        guidance = GUIDANCE.search(message.text)
        what = (guidance.group(1) if guidance else message.situation).rstrip(", ")
        # "Verkehrsbehinderung Baustelle": the second word says it.
        what = re.sub(r"^Verkehrsbehinderung\s+", "", what) or "Verkehrsbehinderung"
    where = stretch(message)
    text = f"{label} {what}" if what == "closed" else f"{label}: {what}"
    text = f"{text}: {where}" if where else text
    return f"{text} ({NO_END})" if period(message)[1] is None else text


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


def occurrences(
    message: Message,
    start: datetime.datetime,
    end: datetime.datetime,
    now: datetime.datetime,
) -> list[tuple[datetime.datetime, datetime.datetime]]:
    """When the message applies between `start` and `end`: once, or for a
    closure only at night or by day, once each day of its period."""
    # Without times: from today, and until the end of each day.
    today = now.astimezone(SWITZERLAND).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    first, last = period(message)
    first = first or today
    if (daily := message.daily) is None:
        until = last or max(today + datetime.timedelta(days=1), now)
        return [(first, until)] if first < end and until > start else []
    out = []
    day = max(first, start - datetime.timedelta(days=1)).astimezone(SWITZERLAND)
    day = day.replace(hour=0, minute=0, second=0, microsecond=0)
    stop = min(end, now + HORIZON, last) if last else min(end, now + HORIZON)
    while day < stop:
        window = day.replace(hour=daily[0].hour, minute=daily[0].minute)
        window_end = day.replace(hour=daily[1].hour, minute=daily[1].minute)
        if window_end <= window:
            # A night runs past midnight.
            window_end = (day + datetime.timedelta(days=1)).replace(
                hour=daily[1].hour, minute=daily[1].minute
            )
        if last:
            window_end = min(window_end, last)
        if (
            window >= first
            and window < window_end
            and window < end
            and window_end > start
        ):
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
    """A calendar's events between `start` and `end`, the first first."""
    out = [
        Event(
            start=s,
            end=e,
            summary=summary(key, message),
            description=description(message, language),
            location=message.location,
            uid=f"{message.identifier}-{s.isoformat()}",
        )
        for message in messages
        if restrictions or is_closure(message)
        for s, e in occurrences(message, start, end, now)
    ]
    return sorted(out, key=lambda event: (event.start, event.summary))
