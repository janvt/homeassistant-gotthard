"""Constants of the Gotthard integration."""

import datetime

DOMAIN = "gotthard"
# The integration's name. The device keeps the short NAME: new entity ids
# are made from it, and dashboards use them.
TITLE = "Gotthard Tunnel Traffic"
NAME = "Gotthard"
USER_AGENT = "homeassistant-gotthard (github.com/janvt/homeassistant-gotthard)"
ATTRIBUTION = "Data: FEDRO (ASTRA) via opentransportdata.swiss"

CONF_API_KEY = "api_key"
API_KEY_URL = "https://api-manager.opentransportdata.swiss"

# The feed is updated every minute, but a key is limited to 260 000 requests
# per six months (about one a minute), shared with whatever else uses it.
UPDATE_INTERVAL = datetime.timedelta(minutes=5)

# The portals' webcams, as shown on tcs.ch.  Both are updated every 5 minutes.
NORTH = "north"
SOUTH = "south"
WEBCAMS = {
    # A2 shortly before Göschenen, looking south towards the tunnel.
    NORTH: "https://webcam.afbn.ch/A_WAS_168,130_S_KAM_001_Sued.jpg",
    # A2 just before the tunnel entrance in Airolo, looking south.
    SOUTH: "https://webcam.afbn.ch/G_AIR_CMAxxxx_x_KAM_001_Sued.jpg",
}
WEBCAM_REFRESH = datetime.timedelta(minutes=1)

# The traffic counters are opt in, in the options, and take a key of their
# own. A key is limited to about one request a minute; one every 2 leaves room
# for a probe.
CONF_COUNTERS = "counters"
CONF_COUNTERS_API_KEY = "counters_api_key"
COUNTERS_INTERVAL = datetime.timedelta(minutes=2)

# The calendars show closures; restrictions (lanes, ramps, roadworks) too
# only when turned on in the options.
CONF_RESTRICTIONS = "restrictions"
