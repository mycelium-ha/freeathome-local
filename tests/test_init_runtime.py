"""Runtime behaviour of a loaded entry: restore, events, reauth, shutdown, actions."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from mock_sysap_server import MockSysApServer
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.freeathome_local.const import (
    CONF_VIRTUAL_DEVICES,
    DOMAIN,
    SERVICE_DUMP_CONFIG,
    SERVICE_SEND_NOTIFICATION,
    SERVICE_TRIGGER_PROXY_DEVICE,
)

from .conftest import SYSAP_SERIAL, SYSAP_UUID, entry_data


async def test_persisted_virtual_devices_are_restored(
    hass: HomeAssistant, mock_sysap: MockSysApServer, caplog: pytest.LogCaptureFixture
) -> None:
    """Saved virtual devices are registered again; broken entries are skipped."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=SYSAP_SERIAL,
        data=entry_data(
            mock_sysap,
            **{
                CONF_VIRTUAL_DEVICES: {
                    "restored": {"device_type": "SwitchingActuator", "ttl": 0},
                    "junk": "junk",
                    "broken": {"ttl": 0},
                }
            },
        ),
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert [rec[1] for rec in mock_sysap.recorded if rec[0] == "PUT_VDEV"] == ["restored"]
    assert "Failed restoring virtual device broken on startup" in caplog.text


async def test_scene_triggered_fires_event(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """`scenesTriggered` frames become `freeathome_local_scene_triggered` events."""
    events = async_capture_events(hass, "freeathome_local_scene_triggered")
    controller = init_integration.runtime_data.controller
    scenes = {"FFFF48000001/ch0000": {"value": "1"}}
    await controller.handle_ws_message({SYSAP_UUID: {"scenesTriggered": scenes}})
    await hass.async_block_till_done()
    assert len(events) == 1
    assert events[0].data == {
        "entry_id": init_integration.entry_id,
        "sysap_uuid": SYSAP_UUID,
        "scenes": scenes,
    }


async def test_websocket_auth_rejection_starts_one_reauth(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A rejected WebSocket login starts a single reauth flow."""
    controller = init_integration.runtime_data.controller
    with patch.object(hass.config_entries, "async_schedule_reload") as reload:
        controller._auth_failed_cb()
        controller._auth_failed_cb()
        await hass.async_block_till_done()
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]
    reload.assert_called_once_with(init_integration.entry_id)


async def test_home_assistant_stop_closes_controller(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Stopping Home Assistant closes the SysAP connection."""
    controller = init_integration.runtime_data.controller
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()
    assert controller.ws_connected is False


async def test_unload_keeps_runtime_when_platforms_fail(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A failed platform unload leaves the controller running."""
    with patch.object(hass.config_entries, "async_unload_platforms", return_value=False):
        assert not await hass.config_entries.async_unload(init_integration.entry_id)
    assert init_integration.runtime_data.controller.ws_connected is True


async def test_proxy_and_notification_actions(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_sysap: MockSysApServer
) -> None:
    """Proxy device and notification actions reach the SysAP, targeted by config entry."""
    await hass.services.async_call(
        DOMAIN,
        SERVICE_TRIGGER_PROXY_DEVICE,
        {
            "device_class": "pushbutton",
            "device_id": "scene_a",
            "action": "shortpress",
            "config_entry_id": init_integration.entry_id,
        },
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SEND_NOTIFICATION,
        {"subject": "Done", "body": "Washing finished", "timeout_minutes": 30},
        blocking=True,
    )
    assert ("PROXY", "pushbutton/scene_a", "shortpress") in mock_sysap.recorded
    notification = next(rec[2] for rec in mock_sysap.recorded if rec[0] == "NOTIFY")
    assert notification["timeoutMinutes"] == 30


async def test_read_only_action_filters_by_entry(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_sysap: MockSysApServer
) -> None:
    """Read-only actions can be limited to one entry and reject unknown entries."""
    with pytest.raises(ServiceValidationError) as exc:
        await hass.services.async_call(
            DOMAIN, SERVICE_DUMP_CONFIG, {"config_entry_id": "missing"}, blocking=True
        )
    assert exc.value.translation_key == "entry_not_loaded"

    await hass.services.async_call(
        DOMAIN,
        SERVICE_DUMP_CONFIG,
        {"config_entry_id": init_integration.entry_id},
        blocking=True,
    )
    dumps = list(Path(hass.config.config_dir).glob("freeathome_local_dump_*.json"))
    assert dumps
    for path in dumps:
        path.unlink()
