"""GTFS static parsing and along-route ETA estimation (no HA imports)."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, datetime
import io
import math
import re
import zipfile

EARTH_R = 6371.0088


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in km."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


def _bearing(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def _secs(t: str) -> int:
    h, m, s = (int(x) for x in t.split(":"))
    return h * 3600 + m * 60 + s


@dataclass
class Route:
    """A route as the user sees it."""

    key: str  # value matched against realtime route_id
    route_ids: set[str]
    short_name: str
    long_name: str

    @property
    def label(self) -> str:
        if self.long_name and self.long_name != self.short_name:
            return f"{self.short_name} - {self.long_name}"
        return self.short_name


@dataclass
class Shape:
    """A route pattern (one direction) with cumulative distances."""

    shape_id: str
    headsign: str
    points: list[tuple[float, float]]
    cum: list[float]  # km along shape at each point
    avg_kmh: float = 18.0
    stops: list[tuple[str, float]] = field(default_factory=list)  # (stop_id, km along)

    def project(self, lat: float, lon: float) -> tuple[float, float, float]:
        """Return (offset_km, along_km, segment_heading) of nearest point."""
        best = (1e9, 0.0, 0.0)
        kx = math.cos(math.radians(lat)) * 111.32
        ky = 110.574
        for i in range(len(self.points) - 1):
            (a_lat, a_lon), (b_lat, b_lon) = self.points[i], self.points[i + 1]
            ax, ay = (a_lon - lon) * kx, (a_lat - lat) * ky
            bx, by = (b_lon - lon) * kx, (b_lat - lat) * ky
            dx, dy = bx - ax, by - ay
            seg2 = dx * dx + dy * dy
            t = 0.0 if seg2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / seg2))
            px, py = ax + t * dx, ay + t * dy
            d = math.hypot(px, py)
            if d < best[0]:
                seg_len = self.cum[i + 1] - self.cum[i]
                best = (d, self.cum[i] + t * seg_len, _bearing(a_lat, a_lon, b_lat, b_lon))
        return best


@dataclass
class Stop:
    stop_id: str
    name: str
    lat: float
    lon: float

    @property
    def short_name(self) -> str:
        """Stop name without the leading stop code (e.g. 'KL1079 KL SENTRAL')."""
        return re.sub(r"^[A-Z]{1,4}\d{2,}[A-Z]?\s+", "", self.name).title()


@dataclass
class RouteDetail:
    route: Route
    shapes: list[Shape]
    stops: dict[str, Stop]


class GtfsStatic:
    """Parsed static feed for one category."""

    def __init__(self, zip_bytes: bytes) -> None:
        self._zip = zipfile.ZipFile(io.BytesIO(zip_bytes))
        self.routes: dict[str, Route] = {}
        self._trips_by_route: dict[str, list[dict]] = {}
        self._details: dict[str, RouteDetail] = {}
        self._load_routes()

    def _rows(self, name: str):
        with self._zip.open(name) as fh:
            yield from csv.DictReader(io.TextIOWrapper(fh, "utf-8-sig"))

    def _load_routes(self) -> None:
        for r in self._rows("routes.txt"):
            rid = r["route_id"].strip()
            short = (r.get("route_short_name") or "").strip()
            long_ = (r.get("route_long_name") or "").strip()
            if not short:  # MRT feeder: number lives in long_name, realtime uses it
                short, long_, key = long_, "", long_
            else:  # RapidKL: realtime uses route_id
                key = rid
            if not key:
                continue
            if key in self.routes:
                self.routes[key].route_ids.add(rid)
            else:
                self.routes[key] = Route(key, {rid}, short, long_)
        rid_to_key = {rid: k for k, r in self.routes.items() for rid in r.route_ids}
        for t in self._rows("trips.txt"):
            key = rid_to_key.get(t["route_id"].strip())
            if key:
                self._trips_by_route.setdefault(key, []).append(t)

    def match_route(self, realtime_route_id: str) -> str | None:
        """Map a realtime route_id to a route key."""
        if realtime_route_id in self.routes:
            return realtime_route_id
        for key, r in self.routes.items():
            if realtime_route_id in r.route_ids or realtime_route_id.split(" ")[0] == key:
                return key
        return None

    def detail(self, key: str) -> RouteDetail:
        """Build shapes + stops for a route (cached)."""
        if key in self._details:
            return self._details[key]
        route = self.routes[key]
        trips = self._trips_by_route.get(key, [])
        rep: dict[str, dict] = {}  # shape_id -> representative trip
        for t in trips:
            rep.setdefault(t.get("shape_id", "").strip(), t)
        rep_trips = {t["trip_id"]: sid for sid, t in rep.items()}

        pts: dict[str, list[tuple[int, float, float]]] = {s: [] for s in rep}
        for r in self._rows("shapes.txt"):
            sid = r["shape_id"].strip()
            if sid in pts:
                pts[sid].append((int(float(r["shape_pt_sequence"])), float(r["shape_pt_lat"]), float(r["shape_pt_lon"])))

        seq: dict[str, list[tuple[int, str, str]]] = {tid: [] for tid in rep_trips}
        for r in self._rows("stop_times.txt"):
            tid = r["trip_id"]
            if tid in seq:
                seq[tid].append((int(r["stop_sequence"]), r["stop_id"].strip(), r.get("arrival_time") or ""))
        stop_ids = {s for v in seq.values() for _, s, _ in v}
        stops: dict[str, Stop] = {}
        for r in self._rows("stops.txt"):
            sid = r["stop_id"].strip()
            if sid in stop_ids:
                stops[sid] = Stop(sid, r["stop_name"].strip(), float(r["stop_lat"]), float(r["stop_lon"]))

        shapes: list[Shape] = []
        for tid, sid in rep_trips.items():
            p = [(la, lo) for _, la, lo in sorted(pts.get(sid, []))]
            if len(p) < 2:
                continue
            cum = [0.0]
            for i in range(1, len(p)):
                cum.append(cum[-1] + haversine(*p[i - 1], *p[i]))
            shape = Shape(sid, (rep[sid].get("trip_headsign") or "").strip(), p, cum)
            st = sorted(seq.get(tid, []))
            for _, stop_id, _ in st:
                s = stops.get(stop_id)
                if s:
                    off, along, _ = shape.project(s.lat, s.lon)
                    if off < 0.15:
                        shape.stops.append((stop_id, along))
            times = [x[2] for x in st if x[2]]
            if len(times) >= 2:
                dur = (_secs(times[-1]) - _secs(times[0])) / 3600
                if dur > 0:
                    shape.avg_kmh = max(8.0, min(40.0, cum[-1] / dur))
            if not shape.headsign and shape.stops:
                shape.headsign = stops[shape.stops[-1][0]].name
            shapes.append(shape)
        detail = RouteDetail(route, shapes, stops)
        self._details[key] = detail
        return detail


def _angle_diff(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def locate(detail: RouteDetail, lat: float, lon: float, bearing: float | None):
    """Best (shape, along_km, offset_km) for a bus, honouring its heading."""
    best = None
    for sh in detail.shapes:
        off, along, heading = sh.project(lat, lon)
        penalty = 0.0
        if bearing is not None and _angle_diff(bearing, heading) > 75:
            penalty = 0.5  # likely the opposite direction
        score = off + penalty
        if best is None or score < best[0]:
            best = (score, sh, along, off)
    if best is None or best[3] > 0.3:
        return None
    return best[1], best[2], best[3]


def eta_to_stop(detail: RouteDetail, stop_id: str, lat: float, lon: float,
                bearing: float | None, speed: float | None):
    """Return (eta_minutes, distance_km, headsign) or None if not approaching."""
    loc = locate(detail, lat, lon, bearing)
    if not loc:
        return None
    shape, along, _ = loc
    stop_along = next((a for s, a in shape.stops if s == stop_id), None)
    if stop_along is None:
        return None
    remaining = stop_along - along
    if remaining < -0.15:
        return None  # already passed (150 m grace covers GPS jitter / buses waiting at the stop)
    remaining = max(0.0, remaining)
    kmh = shape.avg_kmh
    if speed and speed > 5:
        kmh = 0.7 * kmh + 0.3 * min(speed, 60)
    return round(remaining / kmh * 60, 1), round(remaining, 2), shape.headsign


def _simplify(pts: list[tuple[float, float]], tol: float) -> list[tuple[float, float]]:
    """Douglas-Peucker in degrees (tol ~ 0.00005 deg = ~5 m)."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        (y1, x1), (y2, x2) = pts[a], pts[b]
        dx, dy = x2 - x1, y2 - y1
        norm = (dx * dx + dy * dy) ** 0.5 or 1e-12
        best, idx = 0.0, None
        for i in range(a + 1, b):
            y, x = pts[i]
            d = abs(dy * (x - x1) - dx * (y - y1)) / norm
            if d > best:
                best, idx = d, i
        if idx is not None and best > tol:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(pts, keep) if k]


def route_geojson(detail: RouteDetail, tol: float = 0.00005) -> dict:
    """GeoJSON FeatureCollection: one LineString per direction/shape."""
    feats, seen = [], set()
    for sh in detail.shapes:
        if sh.shape_id in seen or len(sh.points) < 2:
            continue
        seen.add(sh.shape_id)
        coords = [[round(lon, 6), round(lat, 6)] for lat, lon in _simplify(sh.points, tol)]
        feats.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {"route": detail.route.short_name, "heading_to": sh.headsign},
        })
    return {"type": "FeatureCollection", "features": feats}


# ---------------------------------------------------------------- timetable

@dataclass
class ScheduledArrival:
    when: "datetime"  # aware, Asia/Kuala_Lumpur
    headsign: str
    frequency_based: bool  # True = derived from frequencies.txt headway (not exact)


@dataclass
class StopSchedule:
    """Timetable for one stop on one route.

    fixed: (service_id, arrival_secs, headsign) from explicit trips (MRT feeder style).
    freq: (service_id, start_secs, end_secs, headway_secs, offset_secs, headsign)
          from frequencies.txt (RapidKL style: a template trip repeated every headway).
    """

    services: dict[str, tuple[set[int], str, str]]  # service_id -> (weekdays, start, end)
    exceptions: dict[tuple[str, str], int]  # (service_id, YYYYMMDD) -> 1 add / 2 remove
    fixed: list[tuple[str, int, str]] = field(default_factory=list)
    freq: list[tuple[str, int, int, int, int, str]] = field(default_factory=list)

    def _active(self, service_id: str, day: "date") -> bool:
        ymd = day.strftime("%Y%m%d")
        exc = self.exceptions.get((service_id, ymd))
        if exc is not None:
            return exc == 1
        svc = self.services.get(service_id)
        return bool(svc and day.weekday() in svc[0] and svc[1] <= ymd <= svc[2])

    def headway_min(self, now: "datetime") -> float | None:
        """Published headway in force now (frequency-based routes only)."""
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        secs = (now - midnight).total_seconds()
        for sid, start, end, hw, _off, _h in self.freq:
            if self._active(sid, now.date()) and start <= secs < end:
                return round(hw / 60, 1)
        return None

    def next_arrivals(self, now: "datetime", count: int = 5, horizon_h: float = 6) -> list[ScheduledArrival]:
        """Next scheduled arrivals after `now` (aware datetime in the feed's zone)."""
        from datetime import timedelta

        out: list[ScheduledArrival] = []
        limit = now + timedelta(hours=horizon_h)
        today = now.date()
        for day_off in (-1, 0, 1):  # GTFS times can exceed 24:00 (yesterday's service)
            day = today + timedelta(days=day_off)
            base = now.replace(year=day.year, month=day.month, day=day.day,
                               hour=0, minute=0, second=0, microsecond=0)
            lo = (now - base).total_seconds()
            hi = (limit - base).total_seconds()
            for sid, secs, head in self.fixed:
                if lo < secs <= hi and self._active(sid, day):
                    out.append(ScheduledArrival(base + timedelta(seconds=secs), head, False))
            for sid, start, end, hw, off, head in self.freq:
                if hw <= 0 or not self._active(sid, day):
                    continue
                # departures at start, start+hw, ... < end; arrival = departure + off
                first = start + off
                k = max(0, math.ceil((lo - first) / hw)) if lo > first else 0
                t = first + k * hw
                while t - off < end and t <= hi:
                    if t > lo:
                        out.append(ScheduledArrival(base + timedelta(seconds=t), head, True))
                    t += hw
        out.sort(key=lambda a: a.when)
        return out[:count]


def build_stop_schedule(static: "GtfsStatic", key: str, stop_id: str) -> StopSchedule:
    """Scan trips/stop_times once for one route + stop (run in executor)."""
    trips = {t["trip_id"]: t for t in static._trips_by_route.get(key, [])}
    services: dict[str, tuple[set[int], str, str]] = {}
    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
    names = set(static._zip.namelist())
    if "calendar.txt" in names:
        for r in static._rows("calendar.txt"):
            services[r["service_id"].strip()] = (
                {i for i, d in enumerate(days) if r.get(d, "0").strip() == "1"},
                r["start_date"].strip(), r["end_date"].strip())
    exceptions: dict[tuple[str, str], int] = {}
    if "calendar_dates.txt" in names:
        for r in static._rows("calendar_dates.txt"):
            exceptions[(r["service_id"].strip(), r["date"].strip())] = int(r["exception_type"])

    first: dict[str, int] = {}  # trip -> earliest time (seconds)
    at_stop: dict[str, list[int]] = {}
    for r in static._rows("stop_times.txt"):
        tid = r["trip_id"]
        if tid not in trips:
            continue
        t = (r.get("arrival_time") or r.get("departure_time") or "").strip()
        if not t:
            continue
        s = _secs(t)
        if tid not in first or s < first[tid]:
            first[tid] = s
        if r["stop_id"].strip() == stop_id:
            at_stop.setdefault(tid, []).append(s)

    freqs: dict[str, list[tuple[int, int, int]]] = {}
    if "frequencies.txt" in names:
        for r in static._rows("frequencies.txt"):
            tid = r["trip_id"]
            if tid in trips:
                freqs.setdefault(tid, []).append(
                    (_secs(r["start_time"]), _secs(r["end_time"]), int(r["headway_secs"])))

    sched = StopSchedule(services, exceptions)
    for tid, times in at_stop.items():
        trip = trips[tid]
        sid = trip["service_id"].strip()
        head = (trip.get("trip_headsign") or "").strip()
        if tid in freqs:
            for t in times:
                off = t - first[tid]
                for start, end, hw in freqs[tid]:
                    sched.freq.append((sid, start, end, hw, off, head))
        else:
            for t in times:
                sched.fixed.append((sid, t, head))
    return sched
