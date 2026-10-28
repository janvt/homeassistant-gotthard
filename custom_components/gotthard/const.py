"""Constants of the Gotthard integration."""

import datetime

DOMAIN = "gotthard"
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
