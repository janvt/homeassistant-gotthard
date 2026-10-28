# Gotthard

A Home Assistant integration for the traffic at the Gotthard road tunnel: the
queues before its portals, whether it is open, its closures to come, and the
webcams at both portals.

The traffic messages are the Swiss Federal Roads Office's (FEDRO / ASTRA),
from [opentransportdata.swiss](https://opentransportdata.swiss).

## Installation

With [HACS](https://hacs.xyz): add this repository as a custom repository of
type *Integration*, install *Gotthard*, and restart Home Assistant.

Or copy `custom_components/gotthard` into your configuration's
`custom_components` folder and restart.

## Configuration

The traffic messages need a free API key:

1. Register at the [API manager](https://api-manager.opentransportdata.swiss).
2. Create an application and subscribe it to **Traffic Situations**.
3. In Home Assistant, go to *Settings → Devices & services → Add integration*,
   choose *Gotthard* and enter the key.

A key is limited to 260 000 requests per six months and expires after six
months unless FEDRO extends it (`verkehrsdaten-plattform@astra.admin.ch`). The
integration asks once every 5 minutes, and asks for a new key when the old one
is refused.

## Entities

| Entity | |
|---|---|
| Tunnel | Open, or closed: at night, for a special transport, after an accident |
| Queue before the north / south portal | km; 0 without a queue, unknown when the message gives no length |
| Delay before the north / south portal | Minutes lost in the queue, as FEDRO reports it |
| Next tunnel closure | When the next planned closure starts; all of them in `closures` |
| Traffic messages | How many messages there are about the Gotthard; their texts in `messages`, in Home Assistant's language where FEDRO gives it |
| North portal (Göschenen), South portal (Airolo) | Webcams on the A2, updated every 5 minutes |

The north portal's queue is the one southbound before Göschenen; the south
portal's is northbound before Airolo.

## How the messages are read

FEDRO's messages give a queue's length and the time it costs only in their
texts, e.g. *"A2 Luzern -> Gotthard zwischen Anschluss Wassen und Anschluss
Göschenen Sachlage: Stau Länge [km] 2.0 … Zeitverlust Anz. [min] 20"*. The
integration reads the German texts: a queue towards the Gotthard that names
Göschenen or Airolo is before that portal, and an A2 message about the tunnel
whose situation is *gesperrt* is a closure. If FEDRO changes its wording, these
may be missed: please open an issue with the message.

## Development

```bash
python3.13 -m venv .venv
.venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest
```

The tests in `tests_live` use the real feed and webcams:

```bash
GOTTHARD_API_KEY=… .venv/bin/pytest -p no:homeassistant -p no:socket tests_live -s
```
