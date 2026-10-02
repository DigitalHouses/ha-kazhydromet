"""Constants for Kazhydromet."""

from datetime import timedelta

DOMAIN = "kazhydromet"
CONF_STATION = "station"
AUTO_STATION = "auto"
WIS2_BASE = "https://wis2box.kazhydromet.kz/oapi"
SYNOP_COLLECTION = (
    "urn:wmo:md:kz-kazhydromet:core.surface-based-observations.synop"
)
UPDATE_INTERVAL = timedelta(minutes=30)
LOOKBACK = timedelta(hours=12)
MAX_AGE = timedelta(hours=4)

WRF_URL = "https://www.kazhydromet.kz/vc/wrf/ftp2/api/forecast_latest.json"
WRF_CACHE_INTERVAL = timedelta(hours=3)
