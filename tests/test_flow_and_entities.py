from pathlib import Path

import aiohttp
import pytest
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from custom_components.prasarana_bus.const import DOMAIN, NO_STOP, PrasaranaService, RT_URL, STATIC_URL
from custom_components.prasarana_bus.diagnostics import async_get_config_entry_diagnostics

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
    active = [s for e, s in states.items() if e.startswith("sensor.") and e.endswith("active_buses")][0]
    assert active.state == "3"
    trackers = [s for e, s in states.items() if e.startswith("device_tracker.")]
    assert len(trackers) == 3 and all("latitude" in t.attributes for t in trackers)
    eta = [s for e, s in states.items() if e.endswith("next_bus_eta")][0]
    assert float(eta.state) > 0 and eta.attributes["plate"] == "VGJ1970"

    entry = hass.config_entries.async_entries(DOMAIN)[0]

    # Verify diagnostics
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["route"]["key"] == "U7510"
    assert diag["realtime"]["active_buses_count"] == 3

    # Verify device_tracker user customization survives reload
    reg = er.async_get(hass)
    tracker_eid = trackers[0].entity_id
    reg.async_update_entity(tracker_eid, name="My Favorite Bus")
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert reg.async_get(tracker_eid).name == "My Favorite Bus"

    # Verify reconfigure flow
    r = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )
    assert r["step_id"] == "reconfigure"
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"stop": NO_STOP})
    assert r["type"] is FlowResultType.ABORT
    assert r["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert entry.data["stop"] == NO_STOP

    # Verify refresh_static service raises HomeAssistantError on network failure without cache
    aioclient_mock.clear_requests()
    aioclient_mock.get(STATIC_URL.format(category="rapid-bus-kl"), exc=aiohttp.ClientError("boom"))
    Path(hass.config.path(".storage", DOMAIN, "rapid-bus-kl.zip")).unlink(missing_ok=True)
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(DOMAIN, PrasaranaService.REFRESH_STATIC, blocking=True)

    assert await hass.config_entries.async_unload(entry.entry_id)
