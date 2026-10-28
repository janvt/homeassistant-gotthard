"""Traffic at the Gotthard, from FEDRO's DATEX II feed of traffic messages.

The feed (opentransportdata.swiss, "Traffic Situations") holds every current
message for Switzerland: queues, closures, roadworks, accidents.  Only those
about the Gotthard road tunnel, its approaches and the pass road are kept.

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

# A message about the Gotthard: its tunnel or pass, a portal town, or a road
# leading to it ("A2 Luzern -> Gotthard").  "A2 Gotthard -> Chiasso" leads away
# and is only kept if it is near a portal.
ABOUT_GOTTHARD = re.compile(
    r"Gotthard-(?:Tunnel|Pass)|Göschenen|Airolo|->\s*Gotthard\b", re.IGNORECASE
)
TOWARDS_GOTTHARD = re.compile(r"(?<!<)->\s*Gotthard\b", re.IGNORECASE)
PORTALS = {NORTH: re.compile(r"Göschenen", re.I), SOUTH: re.compile(r"Airolo", re.I)}
# What the message says has happened: the text from "Sachlage:" to the next
# heading.
SITUATION = re.compile(
    r"Sachlage:\s*(.*?)(?=\s+(?:Länge|Ursache|Zusatz|Dauer|Verkehrsführung)\b|$)"
)
QUEUE = re.compile(r"\bStau\b|stockender Verkehr", re.IGNORECASE)
QUEUE_TYPES = ("stationaryTraffic", "queuingTraffic", "slowTraffic")
# "Tunnel gesperrt", or "gesperrt" alone; not a lane or an exit.
CLOSED = re.compile(r"^(?:Tunnel |Strasse )?gesperrt\b", re.IGNORECASE)
TUNNEL = re.compile(r"Gotthard-Tunnel|Göschenen\b.*\bAirolo|Airolo\b.*\bGöschenen")
# The tunnel's road; the pass road (H2) links the portals too.
A2 = re.compile(r"(?:^|:\s*)A2\b")
LENGTH = re.compile(r"Länge \[km\]\s*(\d+(?:[.,]\d+)?)")
DELAY = re.compile(r"\[min\]\s*(\d+)")
RESCINDED = ("Aufgehoben",)


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

    def is_current(self, now: datetime.datetime) -> bool:
        if self.status == "active":
            return True
        if self.status != "definedByValidityTimeSpec":
            return False
        return (self.start is None or self.start <= now) and (
            self.end is None or now < self.end
        )

    def is_planned(self, now: datetime.datetime) -> bool:
        return self.start is not None and now < self.start


@dataclass(frozen=True)
class Queue:
    """A queue before a portal."""

    length_km: float | None
    delay_min: int | None


@dataclass
class GotthardStatus:
    publication_time: datetime.datetime | None
    queues: dict[str, Queue | None] = field(
        default_factory=lambda: {NORTH: None, SOUTH: None}
    )
    tunnel_closed: bool = False
    # Closures of the tunnel yet to come, the next first.
    planned_closures: list[Message] = field(default_factory=list)
    # Everything current about the Gotthard.
    messages: list[Message] = field(default_factory=list)


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
        text = message.text
        if text.startswith(RESCINDED) or not ABOUT_GOTTHARD.search(text):
            continue
        if _is_tunnel_closure(message):
            if message.is_current(now):
                status.tunnel_closed = True
            elif message.is_planned(now):
                status.planned_closures.append(message)
        if not message.is_current(now):
            continue
        status.messages.append(message)
        if portal := _queue_portal(message):
            status.queues[portal] = _longer(status.queues[portal], _queue(message))
    status.planned_closures.sort(key=lambda message: message.start)
    return status


def _message(element: ET.Element) -> Message:
    validity = element.find(f"{DX2}validity")
    start = end = None
    status = ""
    if validity is not None:
        status = (validity.findtext(f"{DX2}validityStatus") or "").strip()
        spec = validity.find(f"{DX2}validityTimeSpecification")
        if spec is not None:
            starts = [spec.findtext(f"{DX2}overallStartTime")] + [
                period.findtext(f"{DX2}startOfPeriod")
                for period in spec.iter(f"{DX2}validPeriod")
            ]
            ends = [spec.findtext(f"{DX2}overallEndTime")] + [
                period.findtext(f"{DX2}endOfPeriod")
                for period in spec.iter(f"{DX2}validPeriod")
            ]
            start = min(filter(None, map(_time, starts)), default=None)
            end = max(filter(None, map(_time, ends)), default=None)

    texts: dict[str, str] = {}
    for comment in element.iter(f"{DX2}generalPublicComment"):
        for value in comment.iter(f"{DX2}value"):
            if value.text and value.text.strip():
                language = value.get("lang", "")
                text = " ".join(value.text.split())
                texts[language] = (
                    f"{texts[language]} {text}" if language in texts else text
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


def _is_tunnel_closure(message: Message) -> bool:
    return bool(
        A2.search(message.text)
        and TUNNEL.search(message.text)
        and CLOSED.search(message.situation)
    )


def _queue_portal(message: Message) -> str | None:
    """The portal the message's queue is before, if it is about one."""
    if not (
        QUEUE.search(message.situation) or message.abnormal_traffic in QUEUE_TYPES
    ) or not TOWARDS_GOTTHARD.search(message.text):
        return None
    for portal, name in PORTALS.items():
        if name.search(message.text):
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
