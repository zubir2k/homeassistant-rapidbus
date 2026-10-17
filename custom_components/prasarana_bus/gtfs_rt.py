"""Minimal, dependency-free decoder for GTFS-Realtime VehiclePosition feeds.

Avoids pulling gtfs-realtime-bindings/protobuf into Home Assistant (version
conflicts with HA's pinned protobuf). Only the fields we need are decoded.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct


@dataclass
class Vehicle:
    """One bus from the realtime feed."""

    vehicle_id: str
    plate: str
    route_id: str
    trip_id: str
    latitude: float
    longitude: float
    bearing: float | None
    speed: float | None
    timestamp: int


def _varint(buf: bytes, i: int) -> tuple[int, int]:
    shift = result = 0
    while True:
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, i
        shift += 7


def _fields(buf: bytes):
    """Yield (field_number, wire_type, value) for a protobuf message."""
    i, n = 0, len(buf)
    while i < n:
        key, i = _varint(buf, i)
        fnum, wtype = key >> 3, key & 7
        if wtype == 0:
            val, i = _varint(buf, i)
        elif wtype == 1:
            val, i = buf[i : i + 8], i + 8
        elif wtype == 2:
            ln, i = _varint(buf, i)
            val, i = buf[i : i + ln], i + ln
        elif wtype == 5:
            val, i = buf[i : i + 4], i + 4
        else:
            raise ValueError(f"Unsupported wire type {wtype}")
        yield fnum, wtype, val


def _f32(v: bytes) -> float:
    return struct.unpack("<f", v)[0]


def _str(v: bytes) -> str:
    return v.decode("utf-8", "replace")


def _vehicle_position(buf: bytes) -> Vehicle | None:
    trip_id = route_id = vid = plate = label = ""
    lat = lon = None
    bearing = speed = None
    ts = 0
    for f, w, v in _fields(buf):
        if f == 1 and w == 2:  # TripDescriptor
            for tf, tw, tv in _fields(v):
                if tf == 1 and tw == 2:
                    trip_id = _str(tv)
                elif tf == 5 and tw == 2:
                    route_id = _str(tv)
        elif f == 2 and w == 2:  # Position
            for pf, pw, pv in _fields(v):
                if pw != 5:
                    continue
                if pf == 1:
                    lat = _f32(pv)
                elif pf == 2:
                    lon = _f32(pv)
                elif pf == 3:
                    bearing = _f32(pv)
                elif pf == 5:
                    speed = _f32(pv)
        elif f == 5 and w == 0:
            ts = v
        elif f == 8 and w == 2:  # VehicleDescriptor
            for df, dw, dv in _fields(v):
                if dw != 2:
                    continue
                if df == 1:
                    vid = _str(dv)
                elif df == 2:
                    label = _str(dv)
                elif df == 3:
                    plate = _str(dv)
    if lat is None or lon is None or (lat == 0 and lon == 0):
        return None
    plate = plate or label or vid
    return Vehicle(
        vehicle_id=vid or plate,
        plate=plate,
        route_id=route_id,
        trip_id=trip_id,
        latitude=round(lat, 6),
        longitude=round(lon, 6),
        bearing=round(bearing, 1) if bearing is not None else None,
        speed=round(speed, 1) if speed is not None else None,
        timestamp=ts,
    )


def parse_feed(data: bytes) -> tuple[int, list[Vehicle]]:
    """Parse a FeedMessage. Returns (header_timestamp, vehicles)."""
    header_ts = 0
    vehicles: list[Vehicle] = []
    for f, w, v in _fields(data):
        if f == 1 and w == 2:
            for hf, hw, hv in _fields(v):
                if hf == 3 and hw == 0:
                    header_ts = hv
        elif f == 2 and w == 2:
            for ef, ew, ev in _fields(v):
                if ef == 4 and ew == 2:
                    veh = _vehicle_position(ev)
                    if veh and veh.plate:
                        vehicles.append(veh)
    return header_ts, vehicles
