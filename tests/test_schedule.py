"""Timetable fallback: frequencies.txt (RapidKL) based schedule."""
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from custom_components.prasarana_bus.gtfs_static import GtfsStatic, build_stop_schedule

FIX = Path(__file__).parent / "fixtures"
TZ = ZoneInfo("Asia/Kuala_Lumpur")


def test_frequency_schedule() -> None:
    static = GtfsStatic((FIX / "kl_static.zip").read_bytes())
    static.detail("U7510")
    sched = build_stop_schedule(static, "U7510", "1001512")
    weekday = datetime(2026, 10, 19, 17, 30, tzinfo=TZ)
    nxt = sched.next_arrivals(weekday)
    assert len(nxt) == 5 and all(a.frequency_based for a in nxt)
    assert nxt[0].when > weekday and (nxt[1].when - nxt[0].when).total_seconds() == 15 * 60
    assert sched.headway_min(weekday) == 15.0
    # late night: nothing within the horizon after service ends
    assert sched.next_arrivals(datetime(2026, 10, 17, 23, 30, tzinfo=TZ), horizon_h=3) == []
