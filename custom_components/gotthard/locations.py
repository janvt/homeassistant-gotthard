"""Where a message is: its Alert-C codes, placed, and how far from the Gotthard.

The messages only give Alert-C location codes (Switzerland's table 9).
locations.json places the codes the counting stations' table names
(scripts/make_locations.py); a main road's codes run in order along it, so a
code between two placed ones, close by, is placed between them.
"""

from __future__ import annotations

import bisect
import functools
import json
import math
from pathlib import Path

# The Gotthard road tunnel, between its portals.
GOTTHARD = (46.60, 8.59)
# How far apart, in codes, the neighbours of an unplaced code may be.
REACH = 3


@functools.cache
def _table() -> tuple[dict[int, tuple[float, float]], list[int]]:
    data = json.loads((Path(__file__).parent / "locations.json").read_text())
    table = {int(code): (lat, lon) for code, (lat, lon) in data.items()}
    return table, sorted(table)


def place(code: int) -> tuple[float, float] | None:
    table, codes = _table()
    if code in table:
        return table[code]
    i = bisect.bisect_left(codes, code)
    below = codes[i - 1] if i > 0 else None
    above = codes[i] if i < len(codes) else None
    if below is None or above is None or above - below > 2 * REACH:
        return None
    (lat1, lon1), (lat2, lon2) = table[below], table[above]
    return (lat1 + lat2) / 2, (lon1 + lon2) / 2


def km(a: tuple[float, float], b: tuple[float, float] = GOTTHARD) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 6371 * 2 * math.asin(math.sqrt(h))


def distance(codes: tuple[int, ...]) -> float | None:
    """From the Gotthard to the nearest of the codes placed, or None."""
    placed = [p for p in map(place, codes) if p]
    return min(map(km, placed)) if placed else None
