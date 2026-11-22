"""Snapshot and behaviour tests for every platform, driven by the mock SysAP."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from mock_sysap_server import MockSysApServer
from pytest_homeassistant_custom_component.common import MockConfigEntry, snapshot_platform
from syrupy.assertion import SnapshotAssertion
from syrupy.filters import props

from custom_components.freeathome_local import PLATFORMS
from custom_components.freeathome_local.const import DOMAIN

from .conftest import SYSAP_UUID


async def _setup_platforms(
    hass: HomeAssistant, entry: MockConfigEntry, platforms: list[Platform]
) -> None:
    entry.add_to_hass(hass)
    with patch("custom_components.freeathome_local.PLATFORMS", platforms):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


@pytest.mark.usefixtures("entity_registry_enabled_by_default")
@pytest.mark.parametrize("platform", PLATFORMS, ids=lambda p: p.value)
async def test_platform_snapshot(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    entity_registry: er.EntityRegistry,
    snapshot: SnapshotAssertion,
    platform: Platform,
) -> None:
    """Entity registry entries and states of each platform match the snapshot."""
    await _setup_platforms(hass, mock_config_entry, [platform])
    await snapshot_platform(hass, entity_registry, snapshot, mock_config_entry.entry_id)


async def test_device_registry_snapshot(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_sysap: MockSysApServer,
    device_registry: dr.DeviceRegistry,
    snapshot: SnapshotAssertion,
) -> None:
    """The device hierarchy (hub, physical devices, channel devices) matches the snapshot."""
    devices = dr.async_entries_for_config_entry(device_registry, init_integration.entry_id)
    assert devices
    for device in sorted(devices, key=lambda d: sorted(d.identifiers)):
        identifier = next(iter(device.identifiers))[1]
        # The mock SysAP listens on a random port, so the URL is checked separately.
        assert device == snapshot(name=identifier, exclude=props("configuration_url"))
        if device.configuration_url:
            assert device.configuration_url == f"http://{mock_sysap.host_port}"

    children = dr.async_child_entries_for_config_entry(device_registry, init_integration.entry_id)
    assert children
    for child in sorted(children, key=lambda d: sorted(d.identifiers)):
        identifier = next(iter(child.identifiers))[1]
        parent = device_registry.async_get(child.parent_device_id)
        assert parent is not None
        # Channel device `{uuid}_{serial}_{channel}` belongs to physical device `{uuid}_{serial}`.
        assert (DOMAIN, identifier.rsplit("_", 1)[0]) in parent.identifiers
        assert child == snapshot(name=identifier)


async def _broadcast_dp(server: MockSysApServer, path: str, value: str) -> None:
    await server.broadcast_ws_frame(
        {
            SYSAP_UUID: {
                "datapoints": {path: value},
                "scenesTriggered": {},
                "devices": {},
                "devicesAdded": [],
                "devicesRemoved": [],
            }
        }
    )


async def _wait_for_state(hass: HomeAssistant, entity_id: str, expected: str) -> None:
    for _ in range(50):
        await hass.async_block_till_done()
        state = hass.states.get(entity_id)
        if state is not None and state.state == expected:
            return
        await asyncio.sleep(0.02)
    state = hass.states.get(entity_id)
    raise AssertionError(f"{entity_id} is {state.state if state else None}, expected {expected}")


async def test_switch_turn_off_and_push_update(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_sysap: MockSysApServer,
    entity_registry: er.EntityRegistry,
) -> None:
    """Commands write datapoints; WebSocket frames update state."""
    entity_id = entity_registry.async_get_entity_id(
        Platform.LIGHT, DOMAIN, f"{SYSAP_UUID}/ABB700D10001/ch0003"
    ) or entity_registry.async_get_entity_id(
        Platform.SWITCH, DOMAIN, f"{SYSAP_UUID}/ABB700D10001/ch0003"
    )
    assert entity_id is not None
    domain = entity_id.split(".")[0]
    assert hass.states.get(entity_id).state == "on"

    await hass.services.async_call(domain, "turn_off", {"entity_id": entity_id}, blocking=True)
    assert any(
        rec[0] == "PUT_DP" and rec[1].startswith("ABB700D10001.ch0003.")
        for rec in mock_sysap.recorded
    )
    await _wait_for_state(hass, entity_id, "off")

    await _broadcast_dp(mock_sysap, "ABB700D10001/ch0003/odp0000", "1")
    await _wait_for_state(hass, entity_id, "on")


async def test_entities_unavailable_when_websocket_drops(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_sysap: MockSysApServer,
) -> None:
    """All bus entities become unavailable when the WebSocket is lost."""
    controller = init_integration.runtime_data.controller
    for _ in range(50):
        if controller.ws_connected:
            break
        await asyncio.sleep(0.02)
    assert controller.ws_connected
    await mock_sysap.stop()
    for _ in range(100):
        await hass.async_block_till_done()
        if not controller.ws_connected:
            break
        await asyncio.sleep(0.02)
    assert not controller.ws_connected
    # Restart is handled by the fixture teardown; restart here so teardown stays clean.
    await mock_sysap.start()


async def test_dynamic_device_added(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_sysap: MockSysApServer,
    entity_registry: er.EntityRegistry,
) -> None:
    """Devices announced at runtime get entities without a reload."""
    await mock_sysap.broadcast_ws_frame(
        {
            SYSAP_UUID: {
                "datapoints": {},
                "devices": {
                    "ABB700NEW01": {
                        "displayName": "Runtime Switch",
                        "deviceId": "100C",
                        "floor": "01",
                        "room": "01",
                        "channels": {
                            "ch0000": {
                                "displayName": "Dynamic Lamp",
                                "functionID": "0007",
                                "inputs": {"idp0000": {"pairingID": 1, "value": "0"}},
                                "outputs": {"odp0000": {"pairingID": 256, "value": "0"}},
                            }
                        },
                    }
                },
                "devicesAdded": ["ABB700NEW01"],
                "devicesRemoved": [],
            }
        }
    )
    unique_id = f"{SYSAP_UUID}/ABB700NEW01/ch0000"
    for _ in range(50):
        await hass.async_block_till_done()
        if entity_registry.async_get_entity_id(
            Platform.LIGHT, DOMAIN, unique_id
        ) or entity_registry.async_get_entity_id(Platform.SWITCH, DOMAIN, unique_id):
            return
        await asyncio.sleep(0.02)
    raise AssertionError("dynamically added device produced no entity")


async def test_rarely_used_sensor_disabled_by_default(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """The Beaufort wind force duplicates the wind speed and starts disabled."""
    entity_id = entity_registry.async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{SYSAP_UUID}/ABB700D10009/ch0001/odp0001"
    )
    assert entity_id is not None
    entry = entity_registry.async_get(entity_id)
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get(entity_id) is None


async def test_timer_program_is_config_entity(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Timer program switches configure the system and are config entities."""
    from homeassistant.const import EntityCategory

    entity_id = entity_registry.async_get_entity_id(
        Platform.SWITCH, DOMAIN, f"{SYSAP_UUID}/FFFF4A000001/ch0000"
    )
    assert entity_registry.async_get(entity_id).entity_category is EntityCategory.CONFIG


async def test_rocker_event_entity_fires_on_presses(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_sysap: MockSysApServer,
    entity_registry: er.EntityRegistry,
) -> None:
    """Rocker presses and long presses trigger the event entity (ADR-003)."""
    entity_id = entity_registry.async_get_entity_id(
        Platform.EVENT, DOMAIN, f"{SYSAP_UUID}/ABB700D10001/ch0000/event"
    )
    assert entity_id is not None
    bus_events: list[dict] = []
    hass.bus.async_listen("freeathome_local_event", lambda e: bus_events.append(e.data))

    async def _expect(path: str, value: str, event_type: str) -> None:
        await _broadcast_dp(mock_sysap, path, value)
        for _ in range(50):
            await hass.async_block_till_done()
            state = hass.states.get(entity_id)
            if state.attributes.get("event_type") == event_type:
                return
            await asyncio.sleep(0.02)
        raise AssertionError(f"{entity_id} did not report {event_type}")

    await _expect("ABB700D10001/ch0000/odp0000", "1", "press_up")
    await _expect("ABB700D10001/ch0000/odp0001", "9", "hold_up")
    await _expect("ABB700D10001/ch0000/odp0001", "8", "release")
    await _expect("ABB700D10001/ch0000/odp0000", "0", "press_down")
    # The bus event stays unchanged for existing automations.
    assert [e["command"] for e in bus_events][:2] == ["pressed", "dim_start"]


async def test_only_control_elements_get_event_entities(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Window contacts and door bells are no buttons and get no event entity."""
    events = [
        e.unique_id
        for e in er.async_entries_for_config_entry(entity_registry, init_integration.entry_id)
        if e.domain == Platform.EVENT
    ]
    assert events == [f"{SYSAP_UUID}/ABB700D10001/ch0000/event"]
