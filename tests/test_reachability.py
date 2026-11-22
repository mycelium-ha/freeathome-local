"""Entities follow the SysAP's `unresponsive` flag of their device."""

from __future__ import annotations

import copy

import pytest
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from mock_sysap_server import MockSysApServer
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .conftest import SYSAP_UUID, entity_id_for
from .test_platforms import _wait_for_state

SWITCH_DEVICE = "ABB700D10001"
LIGHT = ("light", "ABB700D10002/ch0000")
OTHER_LIGHT = ("light", "ABB700D10002/ch0001")
COVER = ("cover", "ABB700D10003/ch0000")


async def _set_unresponsive(server: MockSysApServer, serial: str, unresponsive: bool) -> None:
    await server.broadcast_ws_frame(
        {SYSAP_UUID: {"devices": {serial: {"unresponsive": unresponsive}}}}
    )


async def test_unresponsive_device_becomes_unavailable(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_sysap: MockSysApServer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """All channels of an unresponsive device go unavailable; other devices stay."""
    light = entity_id_for(hass, *LIGHT)
    state_before = hass.states.get(light).state
    await _set_unresponsive(mock_sysap, "ABB700D10002", True)
    await _wait_for_state(hass, light, STATE_UNAVAILABLE)
    assert hass.states.get(entity_id_for(hass, *OTHER_LIGHT)).state == STATE_UNAVAILABLE
    assert hass.states.get(entity_id_for(hass, *COVER)).state != STATE_UNAVAILABLE
    assert caplog.text.count("ABB700D10002 is unresponsive") == 1

    # Repeating the flag changes nothing and logs nothing.
    await _set_unresponsive(mock_sysap, "ABB700D10002", True)
    await hass.async_block_till_done()
    assert caplog.text.count("ABB700D10002 is unresponsive") == 1

    await _set_unresponsive(mock_sysap, "ABB700D10002", False)
    await _wait_for_state(hass, light, state_before)
    assert "ABB700D10002 is responding again" in caplog.text


async def test_device_unresponsive_at_startup(
    hass: HomeAssistant, mock_sysap: MockSysApServer, mock_config_entry: MockConfigEntry
) -> None:
    """A device the SysAP already reports as unresponsive starts unavailable."""
    config = copy.deepcopy(mock_sysap.configuration)
    config[SYSAP_UUID]["devices"]["ABB700D10002"]["unresponsive"] = True
    mock_sysap.configuration = config
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id_for(hass, *LIGHT)).state == STATE_UNAVAILABLE
    assert hass.states.get(entity_id_for(hass, *COVER)).state != STATE_UNAVAILABLE


async def test_resync_applies_reachability(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_sysap: MockSysApServer
) -> None:
    """After a reconnect, the resynced configuration decides the reachability."""
    controller = init_integration.runtime_data.controller
    mock_sysap.configuration[SYSAP_UUID]["devices"]["ABB700D10002"]["unresponsive"] = True
    await controller.resync_configuration()
    await _wait_for_state(hass, entity_id_for(hass, *LIGHT), STATE_UNAVAILABLE)

    mock_sysap.configuration[SYSAP_UUID]["devices"]["ABB700D10002"]["unresponsive"] = False
    await controller.resync_configuration()
    await hass.async_block_till_done()
    assert hass.states.get(entity_id_for(hass, *LIGHT)).state != STATE_UNAVAILABLE


async def test_reachability_ignores_unknown_and_malformed_updates(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_sysap: MockSysApServer
) -> None:
    """Updates for unknown devices or without a boolean flag are ignored."""
    await mock_sysap.broadcast_ws_frame(
        {
            SYSAP_UUID: {
                "devices": {
                    "ABB7FFFFFFFF": {"unresponsive": True},
                    "ABB700D10002": {"unresponsive": "yes"},
                    SWITCH_DEVICE: "broken",
                }
            }
        }
    )
    await hass.async_block_till_done()
    assert hass.states.get(entity_id_for(hass, *LIGHT)).state != STATE_UNAVAILABLE
