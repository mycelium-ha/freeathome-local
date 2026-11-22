"""Device layout tests for ADR-001: hub -> physical device -> channel device."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.freeathome_local import async_remove_config_entry_device
from custom_components.freeathome_local.const import DOMAIN

from .conftest import SYSAP_UUID

SWITCH_UID = f"{SYSAP_UUID}/ABB700D10001/ch0003"


async def test_existing_install_keeps_entity_ids_and_user_area(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
    area_registry: ar.AreaRegistry,
) -> None:
    """Entities registered on the physical device move to channel devices, keeping ids and areas.

    The user may have moved the physical device to an area of their own choice; channels in
    the same room inherit it.
    """
    mock_config_entry.add_to_hass(hass)
    office = area_registry.async_create("Office")
    physical = device_registry.async_get_or_create(
        config_entry_id=mock_config_entry.entry_id,
        identifiers={(DOMAIN, f"{SYSAP_UUID}_ABB700D10001")},
        name="Living Switch (ABB700D10001)",
    )
    device_registry.async_update_device(physical.id, area_id=office.id)
    entity_registry.async_get_or_create(
        Platform.SWITCH,
        DOMAIN,
        SWITCH_UID,
        config_entry=mock_config_entry,
        device_id=physical.id,
        suggested_object_id="my_ceiling_lamp",
    )

    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    entry = entity_registry.async_get("switch.my_ceiling_lamp")
    assert entry is not None and entry.unique_id == SWITCH_UID
    channel = device_registry.async_get(entry.device_id)
    assert isinstance(channel, dr.ChildDeviceEntry)
    assert channel.parent_device_id == physical.id
    assert channel.name == "Ceiling Lamp"
    # Same room as the physical device: no own area, so the user's area still applies.
    assert channel.area_id is None
    assert dr.async_get_effective_area_id(hass, channel) == office.id
    # The friendly name is unchanged: it was the channel name before and still is.
    assert hass.states.get("switch.my_ceiling_lamp").attributes["friendly_name"] == ("Ceiling Lamp")


async def test_channel_in_other_room_gets_own_area(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """A channel placed in another room than its actuator gets that room as area."""
    entity_id = entity_registry.async_get_entity_id(
        Platform.LIGHT, DOMAIN, f"{SYSAP_UUID}/ABB700D10002/ch0002"
    )
    assert entity_id is not None
    channel = device_registry.async_get(entity_registry.async_get(entity_id).device_id)
    assert isinstance(channel, dr.ChildDeviceEntry)
    assert channel.area_id == "living_room"
    parent = device_registry.async_get(channel.parent_device_id)
    assert parent is not None and parent.area_id == "kitchen"


async def test_secondary_entity_shares_channel_device(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Primary and secondary entities of one channel attach to the same channel device."""
    climate = entity_registry.async_get(
        entity_registry.async_get_entity_id(
            Platform.CLIMATE, DOMAIN, f"{SYSAP_UUID}/ABB700D10004/ch0000"
        )
    )
    temperature = entity_registry.async_get(
        entity_registry.async_get_entity_id(
            Platform.SENSOR, DOMAIN, f"{SYSAP_UUID}/ABB700D10004/ch0000/current_temperature"
        )
    )
    assert climate.device_id == temperature.device_id
    assert climate.has_entity_name and climate.original_name is None
    assert temperature.translation_key == "thermostat_temperature"
    state = hass.states.get(temperature.entity_id)
    assert state.attributes["friendly_name"] == "Room Thermostat Temperature"


async def test_sysap_functions_have_no_channel_device(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """Scenes, groups and timer programs stay single devices named like the function."""
    entity_id = entity_registry.async_get_entity_id(
        Platform.SCENE, DOMAIN, f"{SYSAP_UUID}/FFFF48000001/ch0000"
    )
    device = device_registry.async_get(entity_registry.async_get(entity_id).device_id)
    assert isinstance(device, dr.DeviceEntry)
    assert (DOMAIN, f"{SYSAP_UUID}_FFFF48000001") in device.identifiers
    assert hass.states.get(entity_id).attributes["friendly_name"] == "Movie Night"


async def test_channel_devices_are_protected_from_removal(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Channel devices still present on the SysAP cannot be deleted; stale ones can."""
    entry_id = init_integration.entry_id
    present = device_registry.async_get_child_device_by_identifier(
        (DOMAIN, f"{SYSAP_UUID}_ABB700D10001_ch0003"), entry_id
    )
    assert present is not None
    parent = device_registry.async_get_device_by_identifier(
        (DOMAIN, f"{SYSAP_UUID}_ABB700D10001"), entry_id
    )
    stale = device_registry.async_get_or_create_child(
        config_entry_id=entry_id,
        identifiers={(DOMAIN, f"{SYSAP_UUID}_ABB700D10001_ch0009")},
        parent_device_id=parent.id,
    )
    assert not await async_remove_config_entry_device(hass, init_integration, present)
    assert await async_remove_config_entry_device(hass, init_integration, stale)


async def test_device_removed_on_sysap_is_removed_from_registry(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_sysap,
    device_registry: dr.DeviceRegistry,
    entity_registry: er.EntityRegistry,
) -> None:
    """A `devicesRemoved` frame removes the device, its channel devices and entities."""
    import asyncio

    entry_id = init_integration.entry_id
    fan_uid = f"{SYSAP_UUID}/ABB700D10005/ch0000"
    assert entity_registry.async_get_entity_id(Platform.FAN, DOMAIN, fan_uid) is not None

    await mock_sysap.broadcast_ws_frame(
        {
            SYSAP_UUID: {
                "datapoints": {},
                "devices": {},
                "devicesAdded": [],
                "devicesRemoved": ["ABB700D10005"],
            }
        }
    )
    for _ in range(50):
        await hass.async_block_till_done()
        if entity_registry.async_get_entity_id(Platform.FAN, DOMAIN, fan_uid) is None:
            break
        await asyncio.sleep(0.02)
    assert entity_registry.async_get_entity_id(Platform.FAN, DOMAIN, fan_uid) is None
    assert (
        device_registry.async_get_device_by_identifier(
            (DOMAIN, f"{SYSAP_UUID}_ABB700D10005"), entry_id
        )
        is None
    )
    assert (
        device_registry.async_get_child_device_by_identifier(
            (DOMAIN, f"{SYSAP_UUID}_ABB700D10005_ch0000"), entry_id
        )
        is None
    )


async def test_stale_devices_removed_on_setup(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
) -> None:
    """Devices and channels deleted on the SysAP while HA was down are cleaned up."""
    mock_config_entry.add_to_hass(hass)
    entry_id = mock_config_entry.entry_id
    gone = device_registry.async_get_or_create(
        config_entry_id=entry_id, identifiers={(DOMAIN, f"{SYSAP_UUID}_GONE00000001")}
    )
    kept = device_registry.async_get_or_create(
        config_entry_id=entry_id, identifiers={(DOMAIN, f"{SYSAP_UUID}_ABB700D10001")}
    )
    gone_channel = device_registry.async_get_or_create_child(
        config_entry_id=entry_id,
        identifiers={(DOMAIN, f"{SYSAP_UUID}_ABB700D10001_ch0099")},
        parent_device_id=kept.id,
    )
    # Present in the SysAP configuration, only filtered out (no room): kept.
    filtered_channel = device_registry.async_get_or_create_child(
        config_entry_id=entry_id,
        identifiers={(DOMAIN, f"{SYSAP_UUID}_ABB700D10001_ch0004")},
        parent_device_id=kept.id,
    )

    assert await hass.config_entries.async_setup(entry_id)
    await hass.async_block_till_done()

    assert device_registry.async_get(gone.id) is None
    assert device_registry.async_get(gone_channel.id) is None
    assert device_registry.async_get(kept.id) is not None
    assert device_registry.async_get(filtered_channel.id) is not None
    assert device_registry.async_get_device_by_identifier((DOMAIN, f"hub_{entry_id}"), entry_id)


async def test_setup_with_empty_device_list_removes_nothing(
    hass: HomeAssistant,
    mock_sysap,
    mock_config_entry: MockConfigEntry,
    device_registry: dr.DeviceRegistry,
    caplog,
) -> None:
    """A SysAP that reports no devices at all (for example while booting) keeps the registry."""
    mock_config_entry.add_to_hass(hass)
    entry_id = mock_config_entry.entry_id
    known = device_registry.async_get_or_create(
        config_entry_id=entry_id, identifiers={(DOMAIN, f"{SYSAP_UUID}_ABB700D10001")}
    )
    mock_sysap.configuration[SYSAP_UUID]["devices"] = {}

    assert await hass.config_entries.async_setup(entry_id)
    await hass.async_block_till_done()

    assert device_registry.async_get(known.id) is not None
    assert "reported no devices" in caplog.text
