"""GTFS-Realtime decoder wrapper using python-rapidbus."""
from __future__ import annotations

from rapidbus import (
    Vehicle,
    decode_feed,
    parse_vehicle_position,
)

__all__ = [
    "Vehicle",
    "decode_feed",
    "parse_vehicle_position",
]
