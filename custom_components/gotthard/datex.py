"""Traffic at the Gotthard, from FEDRO's DATEX II feed of traffic messages.

The feed (opentransportdata.swiss, "Traffic Situations") holds every current
message for Switzerland: queues, closures, roadworks, accidents.  Kept are
those about the Gotthard road tunnel, its approaches and the pass road, and
the closures of the A2 and the A4 (the Axenstrasse among them).

The figures are in the messages' texts only: the structured elements for a
queue's length or the time it costs are left empty.  A message reads e.g.

    Freigegeben: A2 Luzern -> Gotthard zwischen Anschluss Wassen und Anschluss
    Göschenen Sachlage: Stau Länge [km] 2.0 Ursache: Verkehrsüberlastung
    Zusatz 1: Zeitverlust Anz. [min] 20

so the German texts are what is matched here.

Source: FEDRO (ASTRA), via opentransportdata.swiss.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import aiohttp

from custom_components.gotthard.const import NORTH, SOUTH, USER_AGENT

_LOGGER = logging.getLogger(__name__)

URL = "https://api.opentransportdata.swiss/TDP/Soap_Datex2/TrafficSituations/Pull"
SOAP_ACTION = (
    "http://opentransportdata.swiss/TDP/Soap_Datex2/Pull/v1/pullTrafficMessages"
)
# The feed covers all of Switzerland, a few MB.
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=60)

DX2 = "{http://datex2.eu/schema/2/2_0}"
XSI_TYPE = "{http://www.w3.org/2001/XMLSchema-instance}type"

# The request is the same every time: a DATEX II pull asks for everything.
REQUEST = """\
<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <d2LogicalModel xmlns="http://datex2.eu/schema/2/2_0"
                    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                    modelBaseVersion="2">
      <exchange>
        <supplierIdentification>
          <country>ch</country>
          <nationalIdentifier>homeassistant-gotthard</nationalIdentifier>
        </supplierIdentification>
      </exchange>
    </d2LogicalModel>
  </soap:Body>
</soap:Envelope>"""

# A message's text holds each language in turn, each opening with its status:
# "Freigegeben: … Libéré: … Approvato: …".
LANGUAGES = {
    "Freigegeben": "de",
    "Aufgehoben": "de",
    "Libéré": "fr",
    "Révoqué": "fr",
    "Approvato": "it",
    "Revocato": "it",
}
LANGUAGE_START = re.compile(rf"\s+(?=(?:{'|'.join(LANGUAGES)}):)")
RESCINDED = ("Aufgehoben",)
# "Freigegeben: A2 Luzern -> Gotthard zwischen Anschluss Wassen und Anschluss
# Göschenen Sachlage: …": the road, its direction, and where on it.  Every
# message on the A2 is labelled "… -> Gotthard" or "Gotthard -> …", so only
# where it is tells whether it is about the Gotthard.
HEADER = re.compile(
    r"^\w+:\s*(?:(?P<road>[AH]\d+)\s+)?(?P<origin>.+?)\s*(?P<arrow><->|->)\s*"
    r"(?P<destination>\S+)\s*(?P<location>.*?)\s*Sachlage:"
)
NEAR_GOTTHARD = re.compile(
    r"Gotthard-(?:Tunnel|Pass)|Göschenen|Airolo|Wassen|Andermatt|Hospental"
    r"|Motto Bartola"
)
PORTALS = {NORTH: re.compile(r"Göschenen"), SOUTH: re.compile(r"Airolo")}
# What the message says has happened: the text from "Sachlage:" to the next
# heading.
SITUATION = re.compile(
    r"Sachlage:\s*(.*?)(?=\s+(?:Länge|Ursache|Zusatz|Dauer|Verkehrsführung"
    r"|Empfehlung)\b|$)"
)
QUEUE = re.compile(r"\bStau\b|stockender Verkehr", re.IGNORECASE)
QUEUE_TYPES = ("stationaryTraffic", "queuingTraffic", "slowTraffic")
# "Strecke gesperrt", "Tunnel gesperrt", or "gesperrt" alone; not a lane, the
# hard shoulder or an exit.
CLOSED = re.compile(r"^(?:Strecke |Tunnel |Strasse )?gesperrt\b", re.IGNORECASE)
TUNNEL = re.compile(r"Gotthard-Tunnel|Göschenen\b.*\bAirolo|Airolo\b.*\bGöschenen")
LENGTH = re.compile(r"Länge \[km\]\s*(\d+(?:[.,]\d+)?)")
DELAY = re.compile(r"\[min\]\s*(\d+)")

# The roads whose closures are kept, their places from north to south as the
# messages name their directions: "A2 Luzern -> Basel" is northbound.
ROADS = {
    "A2": ("Basel", "Luzern", "Gotthard", "Chiasso"),
    "A4": ("Schaffhausen", "Winterthur", "Zürich", "Brunnen", "Altdorf"),
}
BOTH = "both"
# The Axenstrasse is the A4 between Brunnen and Flüelen ("A4 Altdorf <->
# Brunnen zwischen Ortschaft Flüelen und Ortschaft Sisikon").
AXENSTRASSE = re.compile(r"Flüelen|Sisikon|Morschach|Brunnen-Süd|Axen")
# A closure only at night, or only by day, every day of its period: "Dauer:
# nachts voraussichtlich 02.11.2026 22:00 bis 04.11.2026 05:00".
DAILY = re.compile(
    r"Dauer:\s*(?:nachts|tagsüber)\s+voraussichtlich\s+\d\d\.\d\d\.\d{4}\s+"
    r"(\d\d):(\d\d)\s+bis\s+\d\d\.\d\d\.\d{4}\s+(\d\d):(\d\d)"
)
SWITZERLAND = ZoneInfo("Europe/Zurich")


class DatexError(Exception):
    """The messages could not be obtained."""


class AuthError(DatexError):
    """The API key was refused."""


@dataclass(frozen=True)
class Message:
    """One record of the feed."""

    identifier: str
    type: str  # e.g. "AbnormalTraffic"
    abnormal_traffic: str  # e.g. "stationaryTraffic", or ""
    status: str  # "active", "suspended" or "definedByValidityTimeSpec"
    start: datetime.datetime | None
    end: datetime.datetime | None
    texts: dict[str, str]  # by language

    @property
    def text(self) -> str:
        """The German text, which is the one parsed."""
        return self.texts.get("de") or " ".join(self.texts.values())

    def in_language(self, language: str) -> str:
        return self.texts.get(language) or self.text

    @property
    def situation(self) -> str:
        """What has happened, e.g. "Stau" or "Tunnel gesperrt"."""
        match = SITUATION.search(self.text)
        return match.group(1).strip() if match else ""

    @property
    def road(self) -> str:
        """e.g. "A2", or "" for a road without a number."""
        match = HEADER.match(self.text)
        return (match.group("road") or "") if match else ""

    @property
    def towards_gotthard(self) -> bool:
        """On a carriageway leading to the Gotthard, not away or both ways."""
        match = HEADER.match(self.text)
        return bool(
            match and match["arrow"] == "->" and match["destination"] == "Gotthard"
        )

    @property
    def location(self) -> str:
        """Where on the road, e.g. "zwischen Anschluss Wassen und …"."""
        if match := HEADER.match(self.text):
            return match.group("location")
        return self.text.partition("Sachlage:")[0]

    @property
    def direction(self) -> str:
        """NORTH or SOUTH on a road of ROADS, BOTH, or "" on another road."""
        match = HEADER.match(self.text)
        places = ROADS.get(self.road)
        if not (match and places):
            return ""
        if match["arrow"] == "<->":
            return BOTH
        try:
            origin = places.index(match["origin"])
            destination = places.index(match["destination"])
        except ValueError:
            # "A2 Verzweigung Hagnau -> Birsfelden": a place in neither list.
            return BOTH
        return SOUTH if destination > origin else NORTH

    @property
    def daily(self) -> tuple[datetime.time, datetime.time] | None:
        """The hours it applies on each day of its period, if not all day."""
        if match := DAILY.search(self.text):
            start_h, start_m, end_h, end_m = map(int, match.groups())
            return datetime.time(start_h, start_m), datetime.time(end_h, end_m)
        return None

    def _in_period(self, now: datetime.datetime) -> bool:
        # The feed has messages "active" before they start: roadworks
        # announced for next week, say.
        if self.status not in ("active", "definedByValidityTimeSpec"):
            return False
        return (self.start is None or self.start <= now) and (
            self.end is None or now < self.end
        )

    def is_current(self, now: datetime.datetime) -> bool:
        if not self._in_period(now):
            return False
        if (daily := self.daily) is None:
            return True
        start, end = daily
        local = now.astimezone(SWITZERLAND).time()
        # A night runs past midnight.
        return start <= local < end if start < end else local >= start or local < end

    def next_start(self, now: datetime.datetime) -> datetime.datetime | None:
        """When it next applies, if it doesn't now and will."""
        if self.status not in ("active", "definedByValidityTimeSpec"):
            return None
        if self.start is not None and now < self.start:
            return self.start
        daily = self.daily
        if daily is None or not self._in_period(now) or self.is_current(now):
            return None
        start = _at(now, daily[0])
        return start if self.end is None or start < self.end else None

    def end_after(self, start: datetime.datetime) -> datetime.datetime | None:
        """When it ends if it starts, or started, at `start`."""
        if (daily := self.daily) is None:
            return self.end
        end = _at(start, daily[1])
        return min(end, self.end) if self.end else end


@dataclass(frozen=True)
class Queue:
    """A queue before a portal."""

    length_km: float | None
    delay_min: int | None


@dataclass(frozen=True)
class Closure:
    """A message closing a road, from when to when this time."""

    message: Message
    start: datetime.datetime | None
    end: datetime.datetime | None
    direction: str  # NORTH, SOUTH, BOTH, or ""


@dataclass
class Closures:
    current: list[Closure] = field(default_factory=list)
    # Yet to come, the next first.
    planned: list[Closure] = field(default_factory=list)

    @property
    def closed(self) -> bool:
        return bool(self.current)

    def add(self, message: Message, now: datetime.datetime) -> None:
        if message.is_current(now):
            self.current.append(
                Closure(
                    message, message.start, message.end_after(now), message.direction
                )
            )
        elif start := message.next_start(now):
            self.planned.append(
                Closure(message, start, message.end_after(start), message.direction)
            )

    def sort(self) -> None:
        self.planned.sort(key=lambda closure: closure.start)


@dataclass
class GotthardStatus:
    publication_time: datetime.datetime | None
    queues: dict[str, Queue | None] = field(
        default_factory=lambda: {NORTH: None, SOUTH: None}
    )
    tunnel: Closures = field(default_factory=Closures)
    axenstrasse: Closures = field(default_factory=Closures)
    # The full closures of each road of ROADS, by direction.
    roads: dict[str, dict[str, Closures]] = field(
        default_factory=lambda: {
            road: {NORTH: Closures(), SOUTH: Closures()} for road in ROADS
        }
    )
    # Everything current about the Gotthard.
    messages: list[Message] = field(default_factory=list)

    @property
    def tunnel_closed(self) -> bool:
        return self.tunnel.closed

    @property
    def planned_closures(self) -> list[Closure]:
        """The tunnel's."""
        return self.tunnel.planned


class Datex:
    """Client of the traffic messages."""

    def __init__(self, session: aiohttp.ClientSession, api_key: str) -> None:
        self._session = session
        self._api_key = api_key

    async def async_get_status(
        self, now: datetime.datetime | None = None
    ) -> GotthardStatus:
        document = await self._async_pull()
        now = now or datetime.datetime.now(datetime.UTC)
        # Parsing all of Switzerland's messages takes a moment.
        return await asyncio.get_running_loop().run_in_executor(
            None, parse, document, now
        )

    async def _async_pull(self) -> bytes:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": SOAP_ACTION,
            "User-Agent": USER_AGENT,
        }
        try:
            async with self._session.post(
                URL, data=REQUEST.encode(), headers=headers, timeout=REQUEST_TIMEOUT
            ) as response:
                if response.status in (401, 403):
                    raise AuthError(f"API key refused (HTTP {response.status})")
                if response.status != 200:
                    raise DatexError(f"HTTP {response.status} from {URL}")
                return await response.read()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise DatexError(f"Cannot reach {URL}: {err!r}") from err


def parse(document: bytes, now: datetime.datetime) -> GotthardStatus:
    """The Gotthard's traffic, from a pull of the whole feed."""
    try:
        root = ET.fromstring(document)
    except ET.ParseError as err:
        raise DatexError(f"Invalid XML: {err}") from err
    # The publication is in a SOAP envelope, or not.
    publication = next(root.iter(f"{DX2}payloadPublication"), None)
    if publication is None:
        raise DatexError("No payloadPublication in the response")

    status = GotthardStatus(_time(publication.findtext(f"{DX2}publicationTime")))
    for element in publication.iter(f"{DX2}situationRecord"):
        message = _message(element)
        if message.text.startswith(RESCINDED):
            continue
        if message.road in ROADS and _is_closure(message):
            directions = (
                (NORTH, SOUTH) if message.direction == BOTH else (message.direction,)
            )
            for direction in directions:
                status.roads[message.road][direction].add(message, now)
            if message.road == "A4" and AXENSTRASSE.search(message.location):
                status.axenstrasse.add(message, now)
        if not NEAR_GOTTHARD.search(message.location):
            continue
        if _is_tunnel_closure(message):
            status.tunnel.add(message, now)
        if not message.is_current(now):
            continue
        status.messages.append(message)
        if portal := _queue_portal(message):
            status.queues[portal] = _longer(status.queues[portal], _queue(message))
    for closures in (
        status.tunnel,
        status.axenstrasse,
        *(c for road in status.roads.values() for c in road.values()),
    ):
        closures.sort()
    return status


def _message(element: ET.Element) -> Message:
    validity = element.find(f"{DX2}validity")
    start = end = None
    status = ""
    if validity is not None:
        status = (validity.findtext(f"{DX2}validityStatus") or "").strip()
        spec = validity.find(f"{DX2}validityTimeSpecification")
        if spec is not None:
            # A closure announced ahead has the announcement as its overall
            # start and the closure itself as a period: the period wins.
            periods = list(spec.iter(f"{DX2}validPeriod"))
            starts = [p.findtext(f"{DX2}startOfPeriod") for p in periods] or [
                spec.findtext(f"{DX2}overallStartTime")
            ]
            ends = [p.findtext(f"{DX2}endOfPeriod") for p in periods] or [
                spec.findtext(f"{DX2}overallEndTime")
            ]
            start = min(filter(None, map(_time, starts)), default=None)
            end = max(filter(None, map(_time, ends)), default=None)

    texts: dict[str, str] = {}
    for comment in element.iter(f"{DX2}generalPublicComment"):
        for value in comment.iter(f"{DX2}value"):
            if not (value.text and value.text.strip()):
                continue
            # The feed doubles apostrophes in places ("jusqu''à").
            text = " ".join(value.text.split()).replace("''", "'")
            for part in LANGUAGE_START.split(text):
                opening = part.partition(":")[0]
                language = LANGUAGES.get(opening) or value.get("lang", "")
                texts[language] = (
                    f"{texts[language]} {part}" if language in texts else part
                )

    return Message(
        identifier=element.get("id", ""),
        type=element.get(XSI_TYPE, "").rpartition(":")[2],
        abnormal_traffic=(element.findtext(f"{DX2}abnormalTrafficType") or "").strip(),
        status=status,
        start=start,
        end=end,
        texts=texts,
    )


def _time(text: str | None) -> datetime.datetime | None:
    if not text:
        return None
    try:
        return datetime.datetime.fromisoformat(text.strip())
    except ValueError:
        _LOGGER.debug("Ignoring the time %r", text)
        return None


def _at(moment: datetime.datetime, time: datetime.time) -> datetime.datetime:
    """The first `time` of day, Swiss time, after `moment`."""
    local = moment.astimezone(SWITZERLAND)
    at = local.replace(hour=time.hour, minute=time.minute, second=0, microsecond=0)
    return at if at > local else at + datetime.timedelta(days=1)


def _is_closure(message: Message) -> bool:
    """The road closed: not a lane, the hard shoulder, or a ramp."""
    return bool(CLOSED.search(message.situation))


def _is_tunnel_closure(message: Message) -> bool:
    # The pass road (H2) links the portals too.
    return bool(
        message.road == "A2"
        and TUNNEL.search(message.location)
        and _is_closure(message)
    )


def _queue_portal(message: Message) -> str | None:
    """The portal the message's queue is before, if it is about one."""
    if (
        not (QUEUE.search(message.situation) or message.abnormal_traffic in QUEUE_TYPES)
        or not message.towards_gotthard
    ):
        return None
    for portal, name in PORTALS.items():
        if name.search(message.location):
            return portal
    return None


def _queue(message: Message) -> Queue:
    length = LENGTH.search(message.text)
    delay = DELAY.search(message.text)
    return Queue(
        length_km=float(length.group(1).replace(",", ".")) if length else None,
        delay_min=int(delay.group(1)) if delay else None,
    )


def _longer(one: Queue | None, other: Queue) -> Queue:
    """Of two messages about the same portal, the worst figures."""
    if one is None:
        return other
    return Queue(
        length_km=_worst(one.length_km, other.length_km),
        delay_min=_worst(one.delay_min, other.delay_min),
    )


def _worst[T: (int, float)](one: T | None, other: T | None) -> T | None:
    if one is None or other is None:
        return other if one is None else one
    return max(one, other)
