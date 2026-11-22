"""Setup, unload, reload, hub device and service tests against real Home Assistant."""

from __future__ import annotations

import asyncio

import probatio
import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from mock_sysap_server import MockSysApServer
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.freeathome_local import (
    PLATFORMS,
    FreeAtHomeLocalRuntime,
    async_remove_config_entry_device,
)
from custom_components.freeathome_local.const import (
    CONF_NAME_PREFIX,
    CONF_VIRTUAL_DEVICES,
    DOMAIN,
    SERVICE_DUMP_CONFIG,
    SERVICE_MIGRATE_FROM_LEGACY,
    SERVICE_MONITOR,
    SERVICE_REGISTER_VIRTUAL_DEVICE,
    SERVICE_SEND_NOTIFICATION,
    SERVICE_SET_DATAPOINT,
    SERVICE_TRIGGER_PROXY_DEVICE,
    SERVICE_UNREGISTER_VIRTUAL_DEVICE,
)

from .conftest import SYSAP_SERIAL, SYSAP_UUID, entry_data

ALL_SERVICES = (
    SERVICE_DUMP_CONFIG,
    SERVICE_MIGRATE_FROM_LEGACY,
    SERVICE_MONITOR,
    SERVICE_SET_DATAPOINT,
    SERVICE_REGISTER_VIRTUAL_DEVICE,
    SERVICE_UNREGISTER_VIRTUAL_DEVICE,
    SERVICE_TRIGGER_PROXY_DEVICE,
    SERVICE_SEND_NOTIFICATION,
)


async def test_setup_and_unload(
    hass: HomeAssistant, init_integration: MockConfigEntry, device_registry: dr.DeviceRegistry
) -> None:
    """Setup stores runtime data and creates the hub device; services outlive the entry."""
    entry = init_integration
    assert entry.state is ConfigEntryState.LOADED
    assert isinstance(entry.runtime_data, FreeAtHomeLocalRuntime)

    hub = device_registry.async_get_device_by_identifier(
        (DOMAIN, f"hub_{entry.entry_id}"), entry.entry_id
    )
    assert hub is not None
    assert hub.id == entry.runtime_data.hub_device_id
    assert hub.entry_type is dr.DeviceEntryType.SERVICE
    assert hub.serial_number == SYSAP_SERIAL
    assert hub.sw_version == "3.2.1"

    for service in ALL_SERVICES:
        assert hass.services.has_service(DOMAIN, service)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    # Services are registered in async_setup and stay registered (action-setup rule).
    for service in ALL_SERVICES:
        assert hass.services.has_service(DOMAIN, service)


async def test_setup_auth_failure_starts_reauth(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Rejected credentials put the entry into SETUP_ERROR and start a reauth flow."""
    mock_config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        mock_config_entry, data={**mock_config_entry.data, CONF_PASSWORD: "wrong"}
    )
    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    assert mock_config_entry.state is ConfigEntryState.SETUP_ERROR
    flows = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


async def test_setup_unreachable_retries(hass: HomeAssistant, mock_sysap: MockSysApServer) -> None:
    """An unreachable SysAP leads to SETUP_RETRY."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=SYSAP_SERIAL,
        data={"host": "127.0.0.1:1", "username": "apiuser", "password": "secret"},
    )
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_options_change_reloads_entry(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Changing an option reloads the entry and creates a new runtime."""
    old_runtime = init_integration.runtime_data
    hass.config_entries.async_update_entry(init_integration, options={CONF_NAME_PREFIX: "Local "})
    await hass.async_block_till_done()
    assert init_integration.state is ConfigEntryState.LOADED
    assert init_integration.runtime_data is not old_runtime


async def test_suppress_reload_skips_reload(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """While `suppress_reload` is set (migration cutover), option changes do not reload."""
    runtime = init_integration.runtime_data
    runtime.suppress_reload = True
    hass.config_entries.async_update_entry(init_integration, options={CONF_NAME_PREFIX: "Local "})
    await hass.async_block_till_done()
    assert init_integration.runtime_data is runtime


async def test_virtual_device_bookkeeping_does_not_reload(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_sysap: MockSysApServer
) -> None:
    """Registering and unregistering virtual devices persists them without a reload."""
    runtime = init_integration.runtime_data
    await hass.services.async_call(
        DOMAIN,
        SERVICE_REGISTER_VIRTUAL_DEVICE,
        {
            "native_id": "ha_test_switch",
            "device_type": "SwitchingActuator",
            "display_name": "Test Switch",
            "ttl": 180,
        },
        blocking=True,
    )
    await hass.async_block_till_done()
    assert "ha_test_switch" in init_integration.data[CONF_VIRTUAL_DEVICES]
    assert init_integration.runtime_data is runtime
    assert any(rec[0] == "PUT_VDEV" for rec in mock_sysap.recorded)

    await hass.services.async_call(
        DOMAIN, SERVICE_UNREGISTER_VIRTUAL_DEVICE, {"native_id": "ha_test_switch"}, blocking=True
    )
    await hass.async_block_till_done()
    assert "ha_test_switch" not in init_integration.data[CONF_VIRTUAL_DEVICES]
    assert init_integration.runtime_data is runtime


async def test_set_datapoint_service(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_sysap: MockSysApServer
) -> None:
    """`set_datapoint` writes through to the SysAP."""
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SET_DATAPOINT,
        {
            "serialnumber": "ABB700D10001",
            "channel_id": "ch0003",
            "datapoint_id": "idp0000",
            "value": "1",
        },
        blocking=True,
    )
    assert ("PUT_DP", "ABB700D10001.ch0003.idp0000", "1") in mock_sysap.recorded


async def test_services_validate_target(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Actions select a SysAP only through `config_entry_id`; `host` and `entry_id` are rejected."""
    data = {
        "serialnumber": "ABB700D10001",
        "channel_id": "ch0003",
        "datapoint_id": "idp0000",
        "value": "1",
    }
    for field, value in (("host", "10.99.99.99"), ("entry_id", init_integration.entry_id)):
        with pytest.raises(probatio.Invalid):
            await hass.services.async_call(
                DOMAIN, SERVICE_SET_DATAPOINT, {**data, field: value}, blocking=True
            )
    with pytest.raises(probatio.Invalid):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_MIGRATE_FROM_LEGACY,
            {"entry_id": init_integration.entry_id},
            blocking=True,
            return_response=True,
        )


async def test_remove_config_entry_device(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """The hub and present devices are protected; stale devices can be removed."""
    entry = init_integration
    hub = device_registry.async_get_device_by_identifier(
        (DOMAIN, f"hub_{entry.entry_id}"), entry.entry_id
    )
    present = device_registry.async_get_device_by_identifier(
        (DOMAIN, f"{SYSAP_UUID}_ABB700D10001"), entry.entry_id
    )
    stale = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={(DOMAIN, f"{SYSAP_UUID}_REMOVED99")}
    )
    assert hub is not None and present is not None

    assert not await async_remove_config_entry_device(hass, entry, hub)
    assert not await async_remove_config_entry_device(hass, entry, present)
    assert await async_remove_config_entry_device(hass, entry, stale)


async def test_platforms_forwarded(hass: HomeAssistant, init_integration: MockConfigEntry) -> None:
    """Every platform module is loaded and push-only."""
    import importlib

    for platform in PLATFORMS:
        module = importlib.import_module(f"custom_components.freeathome_local.{platform.value}")
        assert module.PARALLEL_UPDATES == 0
        assert platform.value in init_integration.runtime_data.platform_adders


async def test_services_translated_target_errors(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_sysap: MockSysApServer
) -> None:
    """Target resolution errors are translated and name the offending entry."""
    data = {
        "serialnumber": "ABB700D10001",
        "channel_id": "ch0003",
        "datapoint_id": "idp0000",
        "value": "1",
    }
    with pytest.raises(ServiceValidationError) as exc:
        await hass.services.async_call(
            DOMAIN, SERVICE_SET_DATAPOINT, {**data, "config_entry_id": "missing"}, blocking=True
        )
    assert exc.value.translation_domain == DOMAIN
    assert exc.value.translation_key == "entry_not_loaded"
    assert exc.value.translation_placeholders == {"entry_id": "missing"}

    assert await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()
    with pytest.raises(ServiceValidationError) as exc:
        await hass.services.async_call(DOMAIN, SERVICE_SET_DATAPOINT, data, blocking=True)
    assert exc.value.translation_key == "no_loaded_entries"


async def test_entity_action_api_error_is_translated(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_sysap: MockSysApServer,
    entity_registry: er.EntityRegistry,
) -> None:
    """A SysAP error during an entity action surfaces as a translated HomeAssistantError."""
    unique_id = f"{SYSAP_UUID}/ABB700D10001/ch0003"
    entity_id = entity_registry.async_get_entity_id(
        "switch", DOMAIN, unique_id
    ) or entity_registry.async_get_entity_id("light", DOMAIN, unique_id)
    assert entity_id is not None
    mock_sysap.password = "rotated"  # the SysAP now rejects every request

    with pytest.raises(HomeAssistantError) as exc:
        await hass.services.async_call(
            entity_id.split(".")[0], "turn_off", {"entity_id": entity_id}, blocking=True
        )
    assert exc.value.translation_domain == DOMAIN
    assert exc.value.translation_key == "action_failed"
    assert exc.value.translation_placeholders["entity_id"] == entity_id


async def test_writing_service_needs_target_with_several_sysaps(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_sysap: MockSysApServer
) -> None:
    """With two loaded SysAPs a writing action never picks one silently."""
    second = MockConfigEntry(
        domain=DOMAIN,
        unique_id="ABB700000002",
        data=entry_data(mock_sysap),
    )
    second.add_to_hass(hass)
    assert await hass.config_entries.async_setup(second.entry_id)
    await hass.async_block_till_done()

    data = {"subject": "Hi", "body": "Test"}
    with pytest.raises(ServiceValidationError) as exc:
        await hass.services.async_call(DOMAIN, SERVICE_SEND_NOTIFICATION, data, blocking=True)
    assert exc.value.translation_key == "multiple_entries_loaded"

    mock_sysap.recorded.clear()
    await hass.services.async_call(
        DOMAIN,
        SERVICE_SEND_NOTIFICATION,
        {**data, "config_entry_id": second.entry_id},
        blocking=True,
    )
    assert len([rec for rec in mock_sysap.recorded if rec[0] == "NOTIFY"]) == 1


async def test_service_api_error_is_translated(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_sysap: MockSysApServer
) -> None:
    """A SysAP error inside an action surfaces as a translated HomeAssistantError."""
    mock_sysap.password = "rotated"
    with pytest.raises(HomeAssistantError) as exc:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_SET_DATAPOINT,
            {
                "serialnumber": "ABB700D10001",
                "channel_id": "ch0003",
                "datapoint_id": "idp0000",
                "value": "1",
            },
            blocking=True,
        )
    assert exc.value.translation_key == "request_failed"


async def test_entity_services_registered_before_setup(hass: HomeAssistant) -> None:
    """Entity actions are registered by async_setup, before any entry is loaded."""
    from homeassistant.setup import async_setup_component

    assert await async_setup_component(hass, DOMAIN, {})
    for service in ALL_SERVICES:
        assert hass.services.has_service(DOMAIN, service)
    for removed in ("cover_force_position", "thermostat_temperature_correction"):
        assert not hass.services.has_service(DOMAIN, removed)


async def test_unload_stops_websocket_listener(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The WebSocket task is owned by the entry and ends on unload."""
    controller = init_integration.runtime_data.controller
    for _ in range(50):
        if controller.ws_connected:
            break
        await asyncio.sleep(0.02)
    assert controller.ws_connected
    assert await hass.config_entries.async_unload(init_integration.entry_id)
    await hass.async_block_till_done()
    assert not controller.ws_connected
    assert not [
        t
        for t in asyncio.all_tasks()
        if t.get_name() == f"{DOMAIN}_websocket_{init_integration.entry_id}"
    ]


async def test_dump_config_and_monitor_write_files(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_sysap: MockSysApServer
) -> None:
    """Read-only actions write their dump and monitor files into the config folder."""
    from datetime import timedelta
    from pathlib import Path

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    config_dir = Path(hass.config.config_dir)
    await hass.services.async_call(DOMAIN, SERVICE_DUMP_CONFIG, {}, blocking=True)
    assert list(config_dir.glob("freeathome_local_dump_*.json"))

    await hass.services.async_call(
        DOMAIN,
        SERVICE_MONITOR,
        {"duration": 1, "config_entry_id": init_integration.entry_id},
        blocking=True,
    )
    await _broadcast_any_frame(mock_sysap)
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=2))
    await hass.async_block_till_done()
    files = list(config_dir.glob("freeathome_local_monitor_*.jsonl"))
    assert files
    for path in [*files, *config_dir.glob("freeathome_local_dump_*.json")]:
        path.unlink()


async def _broadcast_any_frame(server: MockSysApServer) -> None:
    await server.broadcast_ws_frame(
        {SYSAP_UUID: {"datapoints": {}, "devices": {}, "devicesAdded": [], "devicesRemoved": []}}
    )
    await asyncio.sleep(0.05)


async def test_host_unique_id_is_replaced_by_serial(
    hass: HomeAssistant, mock_sysap: MockSysApServer
) -> None:
    """An entry created without a serial (host as unique ID) gets the serial on setup."""
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=mock_sysap.host_port, data=entry_data(mock_sysap)
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.unique_id == SYSAP_SERIAL
    assert entry.state is ConfigEntryState.LOADED


async def test_host_unique_id_kept_when_serial_belongs_to_another_entry(
    hass: HomeAssistant, mock_sysap: MockSysApServer
) -> None:
    """The serial is not taken over when another entry already uses it."""
    MockConfigEntry(domain=DOMAIN, unique_id=SYSAP_SERIAL, data=entry_data(mock_sysap)).add_to_hass(
        hass
    )
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=mock_sysap.host_port, data=entry_data(mock_sysap)
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.unique_id == mock_sysap.host_port
