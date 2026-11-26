"""Constants for Rapid Bus Tracker."""
from datetime import timedelta
from enum import StrEnum

from rapidbus import (
    CATEGORIES as CATEGORIES,
    FEED_TZ as FEED_TZ,
    RT_URL_TEMPLATE as RT_URL,  # noqa: F401
    STATIC_URL_TEMPLATE as STATIC_URL,  # noqa: F401
)

DOMAIN = "prasarana_bus"


class PrasaranaService(StrEnum):
    """Services for Rapid Bus Tracker."""

    REFRESH_STATIC = "refresh_static"

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
SCHEDULE_HORIZON_H = 6
