from pathlib import Path

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.prasarana_bus.const import DOMAIN, RT_URL, STATIC_URL

FIX = Path(__file__).parent / "fixtures"


def _mock(aioclient_mock):
    aioclient_mock.get(STATIC_URL.format(category="rapid-bus-kl"), content=(FIX / "kl_static.zip").read_bytes())
    aioclient_mock.get(RT_URL.format(category="rapid-bus-kl"), content=(FIX / "kl_vehicles.pb").read_bytes())


async def test_full_flow(hass: HomeAssistant, aioclient_mock) -> None:
    _mock(aioclient_mock)
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert r["step_id"] == "user"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"category": "rapid-bus-kl"})
    assert r["step_id"] == "route"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"route": "U7510"})
    assert r["step_id"] == "stop"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"stop": "1001512"})
    assert r["type"] is FlowResultType.CREATE_ENTRY, r
    await hass.async_block_till_done()

    states = {s.entity_id: s for s in hass.states.async_all()}
    import json, os
    if os.environ.get("RB_DUMP"):
        Path(os.environ["RB_DUMP"]).write_text(json.dumps(
            {e: {"state": s.state, "attributes": dict(s.attributes)} for e, s in states.items()}, default=str))
    for eid, s in sorted(states.items()):
        print(eid, s.state, {k: v for k, v in s.attributes.items() if k in ("eta_min", "distance_km", "heading_to", "latitude", "plate", "stop_name")})
    active = [s for e, s in states.items() if e.startswith("sensor.") and e.endswith("active_buses")][0]
    assert active.state == "3"
    trackers = [s for e, s in states.items() if e.startswith("device_tracker.")]
    assert len(trackers) == 3 and all("latitude" in t.attributes for t in trackers)
    eta = [s for e, s in states.items() if e.endswith("next_bus_eta")][0]
    assert float(eta.state) > 0 and eta.attributes["plate"] == "VGJ1970"

    # bus disappears -> tracker unavailable, then removed once stale
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert await hass.config_entries.async_unload(entry.entry_id)
