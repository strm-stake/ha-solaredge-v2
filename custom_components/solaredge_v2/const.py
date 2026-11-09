"""Constants for the SolarEdge Monitoring API v2 integration."""

from __future__ import annotations

DOMAIN = "solaredge_v2"

API_BASE = "https://monitoringapi.solaredge.com/v2"
TOKEN_URL = f"{API_BASE}/oauth2/token"
AUTHORIZE_URL = "https://connect.solaredge.com/authorize"

# HTTPS relay page that forwards the browser to the local Home Assistant callback.
DEFAULT_REDIRECT_URI = "https://example.com/solaredge-callback.html"
# Extra query parameters for the authorize URL (editable in the config flow).
DEFAULT_AUTHORIZE_EXTRA = "scope=SITE_DATA DEVICE_DATA"

CALLBACK_PATH = "/api/solaredge_v2/callback"

CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"
CONF_REDIRECT_URI = "redirect_uri"
CONF_AUTHORIZE_EXTRA = "authorize_extra"
CONF_SITE_ID = "site_id"
CONF_TOKEN = "token"

CONF_INTERVAL = "update_interval"  # minutes between power polls, 0 = automatic
CONF_BUDGET = "monthly_budget"
CONF_BILLING_DAY = "billing_day"
CONF_TELEMETRY = "device_telemetry"
CONF_DAYLIGHT = "daylight_only"

DEFAULT_INTERVAL = 0
DEFAULT_BUDGET = 1800  # Free tier = 2000 credits / month
DEFAULT_BILLING_DAY = 1
DEFAULT_TELEMETRY = True
DEFAULT_DAYLIGHT = True

TICK_MINUTES = 5
MAX_CALLS_PER_TICK = 8  # free tier allows 10 calls / minute
CALL_SPACING_SECONDS = 1.0
MIN_LIVE_MINUTES = 15  # SolarEdge data has 15-minute resolution
MAX_LIVE_MINUTES = 180
HALF_DAY = 12 * 3600
DAY = 24 * 3600
AFTER_SUNSET_GRACE = 45 * 60  # data lags 15-30 min, keep polling a bit after sunset
SKIP_SECONDS = 7 * 24 * 3600  # optional endpoints answering 4xx are retried after a week
SKIP_SECONDS_CORE = 3600

# key -> (path, parameter kind). Query parameters are documented as from / to /
# resolution (ISO 8601 with time zone; QUARTER_HOUR ... YEAR, TOTAL).
ENDPOINTS: dict[str, tuple[str, str | None]] = {
    "site": ("/sites/{site}", None),
    "overview": ("/sites/{site}/overview", "today"),
    "power": ("/sites/{site}/power", "recent"),
    "energy": ("/sites/{site}/energy", "year_by_month"),
    "lifetime": ("/sites/{site}/lifetime-energy", None),
    "alerts": ("/sites/{site}/alerts", "open"),
    "devices": ("/sites/{site}/devices", "devices"),
    "inverters": ("/sites/{site}/inverters/telemetry", "recent"),
    "meters": ("/sites/{site}/meters/telemetry", "recent"),
    "storage": ("/sites/{site}/storage/telemetry", "recent"),
    "meters_lifetime": ("/sites/{site}/meters/lifetime-energy", "recent"),
    "storage_lifetime": ("/sites/{site}/storage/lifetime-energy", "recent"),
}

# Endpoint -> device type that must exist in the inventory (None = always).
REQUIRES_DEVICE = {
    "meters": "METER",
    "meters_lifetime": "METER",
    "storage": "BATTERY",
    "storage_lifetime": "BATTERY",
}
TELEMETRY_ENDPOINTS = ("inverters", "meters", "storage")
CORE_ENDPOINTS = ("site", "overview", "power")

# Leaves that only describe the request window: never become entities.
NOISE_SUFFIXES = ("_period_from", "_period_to", "_resolution")
# Bucket timestamp of a value: shown as attribute `data_timestamp`, not as entity.
TIMESTAMP_SUFFIX = "_values_timestamp"
