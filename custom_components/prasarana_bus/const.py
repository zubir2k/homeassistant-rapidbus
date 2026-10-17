"""Constants for Prasarana Bus."""
from datetime import timedelta

DOMAIN = "prasarana_bus"

RT_URL = "https://api.data.gov.my/gtfs-realtime/vehicle-position/prasarana/?category={category}"
STATIC_URL = "https://api.data.gov.my/gtfs-static/prasarana?category={category}"

CATEGORIES = {
    "rapid-bus-kl": "RapidKL Bus (Klang Valley)",
    "rapid-bus-mrtfeeder": "MRT Feeder Bus",
    "rapid-bus-kuantan": "Rapid Kuantan",
    "rapid-bus-penang": "Rapid Penang",
}

CONF_CATEGORY = "category"
CONF_ROUTE = "route"
CONF_STOP = "stop"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_STALE_MINUTES = "stale_minutes"
CONF_TIMETABLE_FALLBACK = "timetable_fallback"

DEFAULT_SCAN_INTERVAL = 30
MIN_SCAN_INTERVAL = 15
DEFAULT_STALE_MINUTES = 10
STATIC_MAX_AGE = timedelta(days=7)
NO_STOP = "__none__"
FEED_TZ = "Asia/Kuala_Lumpur"  # agency timezone of all Prasarana feeds
SCHEDULE_HORIZON_H = 6
