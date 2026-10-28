"""Traffic counted on the A2 and A4 around Uri, from FEDRO's counting stations.

The feed (opentransportdata.swiss, "Traffic Counters") has a record per lane
of each station, every minute: the vehicles in that minute as vehicles per
hour, and their average speed, for cars and for lorries. It takes its own API
key. The stations have no names in the feed, only ids and coordinates; the
ones below were placed by their coordinates and Alert-C points, and on both
roads Alert-C's "positive" direction is southbound.

A minute is a few vehicles (flow comes in steps of 60 veh/h), so the readings
are averaged over the last SAMPLES pulls.

Source: FEDRO (ASTRA), via opentransportdata.swiss.
"""

from __future__ import annotations

import asyncio
import datetime
import gzip
import logging
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass, field

import aiohttp

from custom_components.gotthard.const import NORTH, SOUTH, USER_AGENT

_LOGGER = logging.getLogger(__name__)

URL = "https://api.opentransportdata.swiss/TDP/Soap_Datex2/Pull"
SOAP_ACTION = "http://opentransportdata.swiss/TDP/Soap_Datex2/Pull/v1/pullMeasuredData"
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=60)
DX2 = "{http://datex2.eu/schema/2/2_0}"
CAR, LORRY = ("11", "12"), ("21", "22")  # (flow, speed) indexes
# Averaged over this many pulls: 10 minutes at one every 2.
SAMPLES = 5


@dataclass(frozen=True)
class Station:
    key: str  # e.g. "a2_goschenen"
    name: str  # e.g. "A2 Göschenen"
    road: str
    latitude: float
    longitude: float
    # The station's records (one per lane) by direction; ramps left out.
    lanes: dict[str, tuple[str, ...]]


STATIONS = [
    # The A2 from north to south, Nidwalden to the Leventina.
    Station(
        "a2_stans",
        "A2 Stans",
        "A2",
        46.97,
        8.36,
        {SOUTH: ("CH:0616.02", "CH:0616.03"), NORTH: ("CH:0615.02", "CH:0615.03")},
    ),
    Station(
        "a2_buochs",
        "A2 Buochs",
        "A2",
        46.97,
        8.44,
        {SOUTH: ("CH:0613.02", "CH:0613.03"), NORTH: ("CH:0614.02", "CH:0614.03")},
    ),
    Station(
        "a2_seedorf",
        "A2 Seedorf",
        "A2",
        46.89,
        8.60,
        {SOUTH: ("CH:0156.03", "CH:0156.04"), NORTH: ("CH:0156.01", "CH:0156.02")},
    ),
    Station(
        "a2_altdorf",
        "A2 Altdorf",
        "A2",
        46.89,
        8.62,
        {SOUTH: ("CH:0252.04", "CH:0252.05"), NORTH: ("CH:0252.02", "CH:0252.03")},
    ),
    Station(
        "a2_amsteg",
        "A2 Amsteg",
        "A2",
        46.79,
        8.67,
        {SOUTH: ("CH:0195.03", "CH:0195.04"), NORTH: ("CH:0195.01", "CH:0195.02")},
    ),
    Station(
        "a2_gurtnellen",
        "A2 Gurtnellen",
        "A2",
        46.73,
        8.63,
        {SOUTH: ("CH:0528.03", "CH:0528.04"), NORTH: ("CH:0528.01", "CH:0528.02")},
    ),
    Station(
        "a2_wassen",
        "A2 Wassen",
        "A2",
        46.69,
        8.59,
        {SOUTH: ("CH:0529.04", "CH:0529.05"), NORTH: ("CH:0529.02", "CH:0529.03")},
    ),
    Station(
        "a2_goschenen",
        "A2 Göschenen",
        "A2",
        46.67,
        8.59,
        {SOUTH: ("CH:0150.02",), NORTH: ("CH:0150.01",)},
    ),
    Station(
        "a2_quinto",
        "A2 Quinto",
        "A2",
        46.51,
        8.71,
        {SOUTH: ("CH:0293.03", "CH:0293.04"), NORTH: ("CH:0293.01", "CH:0293.02")},
    ),
    # The A4 from Goldau down to the Axenstrasse.
    Station(
        "a4_goldau",
        "A4 Goldau",
        "A4",
        47.05,
        8.56,
        {SOUTH: ("CH:0191.03", "CH:0191.04"), NORTH: ("CH:0191.01", "CH:0191.02")},
    ),
    Station(
        "a4_schwyz",
        "A4 Schwyz",
        "A4",
        47.01,
        8.63,
        {SOUTH: ("CH:0720.03", "CH:0720.04"), NORTH: ("CH:0720.01", "CH:0720.02")},
    ),
    Station(
        "a4_sisikon",
        "A4 Sisikon (Axenstrasse)",
        "A4",
        46.95,
        8.62,
        {SOUTH: ("CH:0120.02",), NORTH: ("CH:0120.01",)},
    ),
]
BY_KEY = {station.key: station for station in STATIONS}
SITES = [
    site for station in STATIONS for lanes in station.lanes.values() for site in lanes
]

# Below this a station counts as slow: a queue forming, before FEDRO says so.
SLOW_KMH = 40
# The Gotthard's approaches, the stations a queue before each portal reaches
# first. Southbound it forms before Göschenen; northbound the first station
# is at Quinto, 8 km before Airolo, so only a long queue shows there.
APPROACH = {SOUTH: ("a2_wassen", "a2_goschenen"), NORTH: ("a2_quinto",)}
# Routes for the travel times: the stations in order and the road km between
# each two (from the map, near enough for an estimate).
ROUTES = {
    "altdorf_goschenen": (
        SOUTH,
        ("a2_altdorf", "a2_amsteg", "a2_gurtnellen", "a2_wassen", "a2_goschenen"),
        (10.0, 7.0, 5.0, 3.0),
    ),
    "goschenen_altdorf": (
        NORTH,
        ("a2_goschenen", "a2_wassen", "a2_gurtnellen", "a2_amsteg", "a2_altdorf"),
        (3.0, 5.0, 7.0, 10.0),
    ),
    "altdorf_stans": (
        NORTH,
        ("a2_altdorf", "a2_seedorf", "a2_buochs", "a2_stans"),
        (2.0, 13.0, 6.0),
    ),
    "stans_altdorf": (
        SOUTH,
        ("a2_stans", "a2_buochs", "a2_seedorf", "a2_altdorf"),
        (6.0, 13.0, 2.0),
    ),
}
# Counted traffic on the Axenstrasse: more than this means it's open,
# whatever the traffic messages say (the feed keeps stale closures).
AXEN_FLOWING = 60


class CountersError(Exception):
    """The counts could not be obtained."""


class CountersAuthError(CountersError):
    """The API key was refused."""


@dataclass(frozen=True)
class Reading:
    """One direction of a station, in one minute or averaged."""

    flow: float  # vehicles per hour
    lorries: float  # of them, lorries per hour
    speed: float | None  # km/h, None without vehicles
    time: datetime.datetime | None = None


def request() -> bytes:
    refs = "".join(
        '<siteRequestReference xsi:type="dx223:_MeasurementSiteRecordVersionedReference" '
        f'targetClass="MeasurementSiteRecord" id="{site}" version="0"/>'
        for site in SITES
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?><soap:Envelope '
        'xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"><soap:Body><d2LogicalModel '
        'xmlns="http://datex2.eu/schema/2/2_0" xmlns:dx223="http://datex2.eu/schema/2/2_0" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" modelBaseVersion="2"><exchange>'
        "<supplierIdentification><country>ch</country><nationalIdentifier>FEDRO</nationalIdentifier>"
        '</supplierIdentification></exchange><payloadPublication xsi:type="dx223:GenericPublication" '
        'lang="en"><publicationCreator><country>ch</country><nationalIdentifier>FEDRO</nationalIdentifier>'
        "</publicationCreator><genericPublicationName>MeasuredDataFilter</genericPublicationName>"
        '<genericPublicationExtension><measuredDataFilter xsi:type="dx223:MeasuredDataFilter">'
        '<measurementSiteTableReference xsi:type="dx223:_MeasurementSiteTableVersionedReference" '
        'targetClass="MeasurementSiteTable" id="OTD:TrafficData" version="0"/>'
        f"{refs}</measuredDataFilter></genericPublicationExtension></payloadPublication>"
        "</d2LogicalModel></soap:Body></soap:Envelope>"
    ).encode()


class Counters:
    """Client of the counts."""

    def __init__(self, session: aiohttp.ClientSession, api_key: str) -> None:
        self._session = session
        self._api_key = api_key

    async def async_get(self) -> dict[tuple[str, str], Reading]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "text/xml; charset=utf-8",
            "SOAPAction": SOAP_ACTION,
            "User-Agent": USER_AGENT,
        }
        try:
            async with self._session.post(
                URL, data=request(), headers=headers, timeout=REQUEST_TIMEOUT
            ) as response:
                if response.status in (401, 403):
                    raise CountersAuthError(f"API key refused (HTTP {response.status})")
                if response.status != 200:
                    raise CountersError(f"HTTP {response.status} from {URL}")
                document = await response.read()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise CountersError(f"Cannot reach {URL}: {err!r}") from err
        return parse(document)


def parse(document: bytes) -> dict[tuple[str, str], Reading]:
    """The minute's reading of each station and direction, from a pull."""
    # Gzipped, with or without saying so in its headers.
    if document[:2] == b"\x1f\x8b":
        document = gzip.decompress(document)
    try:
        root = ET.fromstring(document)
    except ET.ParseError as err:
        raise CountersError(f"Invalid XML: {err}") from err
    lanes: dict[str, dict[str, tuple[float, int]]] = {}
    times: dict[str, datetime.datetime] = {}
    for measurements in root.iter(f"{DX2}siteMeasurements"):
        reference = measurements.find(f"{DX2}measurementSiteReference")
        if reference is None:
            continue
        site = reference.get("id", "")
        values: dict[str, tuple[float, int]] = {}
        for value in measurements.findall(f"{DX2}measuredValue"):
            flow = value.findtext(f".//{DX2}vehicleFlowRate")
            speed = value.find(f".//{DX2}averageVehicleSpeed")
            if flow is not None:
                values[value.get("index", "")] = (float(flow), 0)
            elif speed is not None and speed.findtext(f"{DX2}speed"):
                used = int(speed.get("numberOfInputValuesUsed") or 1)
                values[value.get("index", "")] = (
                    float(speed.findtext(f"{DX2}speed")),
                    used,
                )
        lanes[site] = values
        if when := measurements.findtext(f"{DX2}measurementTimeDefault"):
            times[site] = datetime.datetime.fromisoformat(when)

    readings = {}
    for station in STATIONS:
        for direction, sites in station.lanes.items():
            if not any(site in lanes for site in sites):
                continue
            readings[(station.key, direction)] = _combine(
                [lanes.get(site, {}) for site in sites],
                max((times[s] for s in sites if s in times), default=None),
            )
    return readings


def _combine(lanes: list[dict[str, tuple[float, int]]], time) -> Reading:
    """A direction's lanes: flows added, speeds weighted by their vehicles."""
    flow = lorries = 0.0
    weighted = vehicles = 0.0
    for values in lanes:
        for flow_index, speed_index in (CAR, LORRY):
            flow += values.get(flow_index, (0.0, 0))[0]
            speed, used = values.get(speed_index, (0.0, 0))
            weighted += speed * used
            vehicles += used
        lorries += values.get(LORRY[0], (0.0, 0))[0]
    return Reading(flow, lorries, weighted / vehicles if vehicles else None, time)


@dataclass
class Averages:
    """The last SAMPLES readings of each station and direction."""

    readings: dict[tuple[str, str], deque[Reading]] = field(default_factory=dict)

    def add(self, minute: dict[tuple[str, str], Reading]) -> None:
        for key, reading in minute.items():
            samples = self.readings.setdefault(key, deque(maxlen=SAMPLES))
            # The feed repeats a minute it has nothing newer for.
            if not samples or samples[-1].time != reading.time:
                samples.append(reading)

    def get(self, station: str, direction: str) -> Reading | None:
        samples = self.readings.get((station, direction))
        if not samples:
            return None
        speeds = [(r.speed, r.flow) for r in samples if r.speed is not None]
        weight = sum(flow for _, flow in speeds)
        return Reading(
            flow=sum(r.flow for r in samples) / len(samples),
            lorries=sum(r.lorries for r in samples) / len(samples),
            speed=(sum(s * f for s, f in speeds) / weight) if weight else None,
            time=samples[-1].time,
        )


@dataclass(frozen=True)
class Traffic:
    """What the coordinator hands the entities."""

    stations: dict[tuple[str, str], Reading]
    # A queue forming before each Gotthard portal, by the stations' speeds.
    forming: dict[str, bool]
    axen_flowing: bool | None
    # Minutes, by route.
    travel: dict[str, float | None]


def traffic(averages: Averages) -> Traffic:
    stations = {
        (station.key, direction): reading
        for station in STATIONS
        for direction in (NORTH, SOUTH)
        if (reading := averages.get(station.key, direction)) is not None
    }

    def slow(key: str, direction: str) -> bool:
        reading = stations.get((key, direction))
        return bool(reading and reading.speed is not None and reading.speed < SLOW_KMH)

    axen = [stations.get(("a4_sisikon", d)) for d in (NORTH, SOUTH)]
    return Traffic(
        stations=stations,
        forming={d: any(slow(key, d) for key in keys) for d, keys in APPROACH.items()},
        axen_flowing=None if None in axen else sum(r.flow for r in axen) > AXEN_FLOWING,
        travel={route: _travel(stations, *spec) for route, spec in ROUTES.items()},
    )


def _travel(stations, direction, keys, kms) -> float | None:
    """Minutes along the route, each stretch at the mean of its two ends' speeds."""
    minutes = 0.0
    for (start, end), km in zip(zip(keys, keys[1:]), kms):
        speeds = [
            r.speed
            for k in (start, end)
            if (r := stations.get((k, direction))) and r.speed is not None
        ]
        if not speeds:
            return None
        minutes += km / (sum(speeds) / len(speeds)) * 60
    return minutes
