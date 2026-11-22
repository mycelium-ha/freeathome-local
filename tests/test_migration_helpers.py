"""Pure helpers of the legacy takeover: parsing, filtering and legacy entry matching."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity_registry import RegistryEntryDisabler
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.freeathome_local.const import CONF_SWITCH_AS_X, DOMAIN
from custom_components.freeathome_local.migration import (
    LegacyDeviceInfo,
    _candidate_sysap_uuids,
    _extract_aliases,
    _extract_entity_options,
    _is_user_reason,
    _legacy_config_entries,
    _lookup_device,
    _transfer_device_metadata,
    discover_legacy_devices,
    find_matching_legacy_entry,
    get_legacy_setup_defaults,
    parse_serialnumbers_text,
)

LEGACY = "freeathome"
DEFAULT_UUID = "00000000-0000-0000-0000-000000000000"


def _legacy(hass: HomeAssistant, unique_id: str | None, host: str, **data: Any) -> MockConfigEntry:
    entry = MockConfigEntry(domain=LEGACY, unique_id=unique_id, data={CONF_HOST: host, **data})
    entry.add_to_hass(hass)
    return entry


def test_parse_serialnumbers_text() -> None:
    """Serials are split on commas and whitespace, upper-cased and de-duplicated."""
    assert parse_serialnumbers_text(" abb1, ABB1\nabb2  abb3,,") == ["ABB1", "ABB2", "ABB3"]
    assert parse_serialnumbers_text("   ") == []


@pytest.mark.parametrize(
    ("reason", "expected"),
    [(None, False), (RegistryEntryDisabler.USER, True), ("integration", False), ("USER", True)],
)
def test_is_user_reason(reason: Any, expected: bool) -> None:
    """Only user-made disable/hide reasons are carried over."""
    assert _is_user_reason(reason) is expected


def test_extract_entity_options_and_aliases() -> None:
    """Legacy-only and default options are dropped; aliases need a real string."""
    assert _extract_entity_options(None) == {}
    assert _extract_entity_options(
        {
            LEGACY: {"x": 1},
            1: {"x": 1},
            "light": "junk",
            "sensor": {"suggested_display_precision": 2},
            "conversation": {"should_expose": True},
        }
    ) == {"conversation": {"should_expose": True}}
    assert _extract_aliases(None) is None
    assert _extract_aliases(["", None]) is None
    assert _extract_aliases(["Lamp", "Lamp", None]) == ["Lamp", None]


async def test_lookup_device_needs_entry(
    hass: HomeAssistant, device_registry: dr.DeviceRegistry
) -> None:
    """Device lookups without an owning entry find nothing."""
    assert _lookup_device(device_registry, LEGACY, "x", config_entry_id=None) is None
    assert _legacy_config_entries(None) == []


async def test_find_matching_legacy_entry(hass: HomeAssistant) -> None:
    """Legacy entries match by serial first, then host, then as the only one."""
    hub = MockConfigEntry(domain=DOMAIN, unique_id="abb700999999", data={CONF_HOST: "SysAP.local"})
    assert find_matching_legacy_entry(hass, hub) is None

    only = _legacy(hass, None, "other.local")
    assert find_matching_legacy_entry(hass, hub) is only

    by_host = _legacy(hass, None, "sysap.local")
    assert find_matching_legacy_entry(hass, hub) is by_host

    by_serial = _legacy(hass, "ABB700999999", "x.local")
    assert find_matching_legacy_entry(hass, hub) is by_serial

    stranger = MockConfigEntry(domain=DOMAIN, unique_id=None, data={CONF_HOST: "nowhere"})
    assert find_matching_legacy_entry(hass, stranger) is None


async def test_get_legacy_setup_defaults(hass: HomeAssistant) -> None:
    """Setup defaults are read from the legacy entry matching serial or host."""
    assert get_legacy_setup_defaults(hass, host="sysap.local") == {}

    _legacy(hass, "ABB700000001", "first.local", use_room_names=1)
    assert get_legacy_setup_defaults(hass) == {CONF_HOST: "first.local"}
    _legacy(hass, "ABB700000002", "second.local", **{CONF_SWITCH_AS_X: 0})
    assert get_legacy_setup_defaults(hass) == {}
    assert get_legacy_setup_defaults(hass, serial_number="abb700000002") == {
        CONF_HOST: "second.local",
        CONF_SWITCH_AS_X: False,
    }
    assert get_legacy_setup_defaults(hass, serial_number="none", host="FIRST.local") == {
        CONF_HOST: "first.local"
    }


def test_candidate_sysap_uuids() -> None:
    """SysAP UUIDs come from the controller, with the primary UUID as fallback."""

    def _hub(**controller: Any) -> Any:
        return SimpleNamespace(
            runtime_data=SimpleNamespace(controller=SimpleNamespace(**controller))
        )

    assert _candidate_sysap_uuids(SimpleNamespace()) == [DEFAULT_UUID]  # type: ignore[arg-type]
    assert _candidate_sysap_uuids(_hub(sysap_uuids=["a", "b"])) == ["a", "b"]
    assert _candidate_sysap_uuids(_hub(sysap_uuids=[], primary_sysap_uuid="p")) == ["p"]
    assert _candidate_sysap_uuids(_hub(sysap_uuids=[], primary_sysap_uuid="")) == [DEFAULT_UUID]


async def test_discover_legacy_devices_edges(hass: HomeAssistant) -> None:
    """Discovery needs hass, skips devices without a legacy serial and honours the filter."""
    assert discover_legacy_devices(None, None) == []
    legacy = _legacy(hass, "SERIAL1", "192.0.2.10")
    dev_reg = dr.async_get(hass)
    dev_reg.async_get_or_create(
        config_entry_id=legacy.entry_id, identifiers={(LEGACY, "ABB700D10001")}
    )
    dev_reg.async_get_or_create(
        config_entry_id=legacy.entry_id, identifiers={("other_domain", "ABB700D10002")}
    )
    found = discover_legacy_devices(hass, legacy)
    assert [dev.serialnumber for dev in found] == ["ABB700D10001"]
    assert discover_legacy_devices(hass, legacy, serialnumbers_filter={"ABB700D10003"}) == []


async def test_transfer_device_metadata_without_user_changes(hass: HomeAssistant) -> None:
    """A legacy device without name, area or labels changes nothing on the free@home Local device."""
    hub = MockConfigEntry(domain=DOMAIN)
    hub.add_to_hass(hass)
    dev_reg = dr.async_get(hass)
    target_dev = dev_reg.async_get_or_create(
        config_entry_id=hub.entry_id, identifiers={(DOMAIN, f"{DEFAULT_UUID}_ABB700D10001")}
    )
    legacy = LegacyDeviceInfo(
        serialnumber="ABB700D10001", entry_id=None, device_registry_id=None, title="Switch"
    )
    assert _transfer_device_metadata(dev_reg, target_dev, legacy) is None
    assert dev_reg.async_get(target_dev.id).name_by_user is None
