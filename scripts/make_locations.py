"""Writes custom_components/gotthard/locations.json: Alert-C location codes
(Switzerland's table 9) and their coordinates.

The traffic messages only give codes. Switzerland's location table isn't
published, but the counting stations' table names the same codes with the
stations' coordinates, and that covers most of the A2 and A4. Codes between
two of them are placed between them when the messages are read.

    .venv/bin/python scripts/make_locations.py TABLE.xml

TABLE.xml is the counters' station table (pullMeasurementSiteTable), as the
traffic counters' key fetches it. Coordinates are as the table has them, to
0.01°.
"""

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

DX2 = "{http://datex2.eu/schema/2/2_0}"
OUT = (
    Path(__file__).resolve().parent.parent
    / "custom_components"
    / "gotthard"
    / "locations.json"
)


def main(table: str) -> None:
    codes: dict[int, list[float]] = {}
    for site in ET.parse(table).getroot().iter(f"{DX2}measurementSiteRecord"):
        lat = site.findtext(f".//{DX2}latitude")
        lon = site.findtext(f".//{DX2}longitude")
        if not (lat and lon):
            continue
        for code in site.iter(f"{DX2}specificLocation"):
            if code.text and code.text.strip().isdigit():
                codes.setdefault(int(code.text), [float(lat), float(lon)])
    OUT.write_text(
        json.dumps({str(c): codes[c] for c in sorted(codes)}, separators=(",", ":"))
        + "\n"
    )
    print(f"{len(codes)} codes to {OUT}")


if __name__ == "__main__":
    main(sys.argv[1])
