"""Tests for guided legacy `freeathome` -> `freeathome_local` migration (real HA registries)."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.config_entries import HANDLERS, ConfigEntryState, ConfigFlow
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import label_registry as lr
from homeassistant.helpers.entity_registry import (
    COMPUTED_NAME,
    RegistryEntryDisabler,
    RegistryEntryHider,
)
from homeassistant.setup import async_setup_component
from mock_sysap_server import MockSysApServer
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockModule,
    mock_integration,
    mock_platform,
)

from custom_components.freeathome_local import FreeAtHomeLocalRuntime
from custom_components.freeathome_local.const import (
    CONF_NAME_PREFIX,
    CONF_SWITCH_AS_X,
    DOMAIN,
    LEGACY_DOMAIN,
    SERVICE_MIGRATE_FROM_LEGACY,
)
from custom_components.freeathome_local.migration import (
    ParsedLegacyUniqueId,
    async_migrate_from_legacy,
    get_legacy_setup_defaults,
    parse_legacy_unique_id,
)

from .conftest import entry_data

SYSAP_UUID = "00000000-0000-0000-0000-000000000000"
LEGACY_SERIAL = "ABB700D86147"


@dataclass
class Env:
    """Registries and entries of one migration scenario."""

    hub_entry: MockConfigEntry
    legacy_entry: MockConfigEntry
    dev_reg: dr.DeviceRegistry
    ent_reg: er.EntityRegistry
    devices: dict[str, str]  # key -> device_id


def _entity(
    ent_reg: er.EntityRegistry,
    *,
    entity_id: str,
    unique_id: str,
    platform: str,
    config_entry: MockConfigEntry | None = None,
    device_id: str | None = None,
    options: dict[str, dict[str, Any]] | None = None,
    **updates: Any,
) -> str:
    domain, object_id = entity_id.split(".", 1)
    entry = ent_reg.async_get_or_create(
        domain,
        platform,
        unique_id,
        config_entry=config_entry,
        device_id=device_id,
        suggested_object_id=object_id,
    )
    assert entry.entity_id == entity_id
    if updates:
        ent_reg.async_update_entity(entity_id, **updates)
    for opt_domain, values in (options or {}).items():
        ent_reg.async_update_entity_options(entity_id, opt_domain, values)
    return entity_id


def _build_env(
    hass: HomeAssistant,
    *,
    target_switch_as_x: bool = True,
    legacy_switch_as_x: bool = True,
    name_prefix: str = "",
) -> Env:
    """Create a legacy entry, a free@home Local hub entry and matching registry content."""
    dev_reg = dr.async_get(hass)
    ent_reg = er.async_get(hass)
    area_reg = ar.async_get(hass)
    label_reg = lr.async_get(hass)
    area_reg.async_create("bad")
    for label in ("licht", "bad", "target", "wichtig", "existing_target"):
        label_reg.async_create(label)

    legacy_entry = MockConfigEntry(
        domain=LEGACY_DOMAIN,
        title="192.168.8.23",
        unique_id=LEGACY_SERIAL,
        data={
            CONF_HOST: "192.168.8.23",
            "use_room_names": False,
            CONF_SWITCH_AS_X: legacy_switch_as_x,
        },
    )
    legacy_entry.add_to_hass(hass)
    hub_entry = MockConfigEntry(
        domain=DOMAIN,
        title="SysAP Local",
        unique_id=LEGACY_SERIAL,
        data={
            CONF_HOST: "192.168.8.23",
            CONF_SWITCH_AS_X: target_switch_as_x,
            CONF_NAME_PREFIX: name_prefix,
        },
    )
    hub_entry.add_to_hass(hass)
    hub_entry.runtime_data = FreeAtHomeLocalRuntime(
        controller=SimpleNamespace(  # type: ignore[arg-type]
            sysap_uuids=[SYSAP_UUID],
            primary_sysap_uuid=SYSAP_UUID,
            sysap_serial=LEGACY_SERIAL,
            client=SimpleNamespace(host="192.168.8.23"),
        ),
        entry=hub_entry,
    )

    def _device(entry: MockConfigEntry, identifier: tuple[str, str], **kw: Any) -> str:
        name_by_user = kw.pop("name_by_user", None)
        area_id = kw.pop("area_id", None)
        labels = kw.pop("labels", None)
        device = dev_reg.async_get_or_create(
            config_entry_id=entry.entry_id, identifiers={identifier}, **kw
        )
        dev_reg.async_update_device(
            device.id,
            name_by_user=name_by_user,
            area_id=area_id,
            labels=labels or set(),
        )
        return device.id

    devices = {
        "leg_switch": _device(
            legacy_entry,
            (LEGACY_DOMAIN, "ABB700DA1DDF"),
            name="Bad Doppeltaster",
            name_by_user="Mein Bad Doppeltaster",
            area_id="bad",
            labels={"licht", "bad"},
        ),
        "target_switch": _device(
            hub_entry,
            (DOMAIN, f"{SYSAP_UUID}_ABB700DA1DDF"),
            name="Bad Doppeltaster (ABB700DA1DDF)",
            labels={"target"},
        ),
        "leg_rt": _device(
            legacy_entry, (LEGACY_DOMAIN, "ABB700DB3F2C"), name="Bad RTRegler", area_id="bad"
        ),
        "target_rt": _device(
            hub_entry, (DOMAIN, f"{SYSAP_UUID}_ABB700DB3F2C"), name="Bad RTRegler (ABB700DB3F2C)"
        ),
    }

    # Legacy entities (switch, dimmer status, thermostat temperature, scene, multi-sensor)
    _entity(
        ent_reg,
        entity_id="switch.bad_deckenlicht",
        unique_id="ABB700DA1DDF/ch0006",
        platform=LEGACY_DOMAIN,
        config_entry=legacy_entry,
        device_id=devices["leg_switch"],
        name="Deckenlicht Custom",
        icon="mdi:ceiling-light",
        area_id="bad",
        aliases=["Bad Licht", COMPUTED_NAME],
        labels={"wichtig"},
        options={
            "conversation": {"should_expose": True},
            "cloud.google_assistant": {"should_expose": False},
            LEGACY_DOMAIN: {"ignored": True},
        },
    )
    _entity(
        ent_reg,
        entity_id="sensor.bad_dimming_status",
        unique_id="ABB700DA1DDF/ch0000/dimming_status",
        platform=LEGACY_DOMAIN,
        config_entry=legacy_entry,
        device_id=devices["leg_switch"],
        disabled_by=RegistryEntryDisabler.USER,
        hidden_by=RegistryEntryHider.USER,
        aliases=[COMPUTED_NAME],
    )
    _entity(
        ent_reg,
        entity_id="sensor.bad_rt_temp",
        unique_id="ABB700DB3F2C/ch0000/current_temperature",
        platform=LEGACY_DOMAIN,
        config_entry=legacy_entry,
        device_id=devices["leg_rt"],
        disabled_by=RegistryEntryDisabler.INTEGRATION,
        hidden_by=RegistryEntryHider.INTEGRATION,
        options={
            "sensor": {"suggested_display_precision": 1, "display_precision": 2},
            "conversation": {"should_expose": True},
        },
    )
    _entity(
        ent_reg,
        entity_id="scene.abdunkeln",
        unique_id=f"{LEGACY_SERIAL}/FFFF48000002/ch0000",
        platform=LEGACY_DOMAIN,
        config_entry=legacy_entry,
        options={"conversation": {"should_expose": True}},
    )
    _entity(
        ent_reg,
        entity_id="sensor.living_co2",
        unique_id="ABB700D10007/ch0000/odp0001",
        platform=LEGACY_DOMAIN,
        config_entry=legacy_entry,
        options={"sensor": {"suggested_display_precision": 0}},
    )

    # Matching free@home Local entities
    target_switch_domain = "switch" if target_switch_as_x else "light"
    _entity(
        ent_reg,
        entity_id=f"{target_switch_domain}.target_bad_deckenlicht",
        unique_id=f"{SYSAP_UUID}/ABB700DA1DDF/ch0006",
        platform=DOMAIN,
        config_entry=hub_entry,
        device_id=devices["target_switch"],
        labels={"existing_target"},
    )
    _entity(
        ent_reg,
        entity_id="sensor.target_bad_dimming_status",
        unique_id=f"{SYSAP_UUID}/ABB700DA1DDF/ch0000/dimming_status",
        platform=DOMAIN,
        config_entry=hub_entry,
        device_id=devices["target_switch"],
    )
    _entity(
        ent_reg,
        entity_id="sensor.target_bad_rt_temp",
        unique_id=f"{SYSAP_UUID}/ABB700DB3F2C/ch0000/current_temperature",
        platform=DOMAIN,
        config_entry=hub_entry,
        device_id=devices["target_rt"],
    )
    _entity(
        ent_reg,
        entity_id="scene.target_abdunkeln",
        unique_id=f"{SYSAP_UUID}/FFFF48000002/ch0000",
        platform=DOMAIN,
        config_entry=hub_entry,
    )
    _entity(
        ent_reg,
        entity_id="sensor.target_living_co2",
        unique_id=f"{SYSAP_UUID}/ABB700D10007/ch0000/odp0001",
        platform=DOMAIN,
        config_entry=hub_entry,
    )

    # Helper entities that must remain completely untouched
    _entity(
        ent_reg,
        entity_id="light.bad_deckenlicht",
        unique_id="helper_switch_as_x_1",
        platform="switch_as_x",
        device_id=devices["leg_switch"],
    )
    _entity(
        ent_reg,
        entity_id="sensor.bad_heizbedarf_heute",
        unique_id="helper_utility_1",
        platform="utility_meter",
        device_id=devices["leg_rt"],
    )

    return Env(hub_entry, legacy_entry, dev_reg, ent_reg, devices)


def _legacy_entries(hass: HomeAssistant) -> list[str]:
    return [e.entry_id for e in hass.config_entries.async_entries(LEGACY_DOMAIN)]


def test_parse_legacy_unique_id_formats() -> None:
    """Verify parsing of hardware, suffix, multi-sensor, and SysAP-prefixed IDs."""
    assert parse_legacy_unique_id("ABB700DA1DDF/ch0006") == ParsedLegacyUniqueId(
        serialnumber="ABB700DA1DDF", channel_id="ch0006", suffix=""
    )
    assert parse_legacy_unique_id("ABB700DA1DDF/ch0000/dimming_status") == ParsedLegacyUniqueId(
        serialnumber="ABB700DA1DDF",
        channel_id="ch0000",
        suffix="/dimming_status",
    )
    assert parse_legacy_unique_id(
        "ABB700DB3F2C/ch0000/current_temperature"
    ) == ParsedLegacyUniqueId(
        serialnumber="ABB700DB3F2C",
        channel_id="ch0000",
        suffix="/current_temperature",
    )
    assert parse_legacy_unique_id("ABB700D10007/ch0000/odp0001") == ParsedLegacyUniqueId(
        serialnumber="ABB700D10007",
        channel_id="ch0000",
        suffix="/odp0001",
    )
    assert parse_legacy_unique_id("ABB700D86147/FFFF48000002/ch0000") == ParsedLegacyUniqueId(
        serialnumber="FFFF48000002",
        channel_id="ch0000",
        suffix="",
        sysap_prefix="ABB700D86147",
    )
    assert parse_legacy_unique_id("FFFF48000002/ch0000") == ParsedLegacyUniqueId(
        serialnumber="FFFF48000002", channel_id="ch0000", suffix=""
    )
    assert parse_legacy_unique_id("invalid_unique_id") is None
    assert parse_legacy_unique_id("ABB700DA1DDF/bad_channel") is None


async def test_dry_run_preview_non_destructive(hass: HomeAssistant) -> None:
    """dry_run=True performs zero writes and surfaces mismatch/prefix warnings."""
    env = _build_env(hass, target_switch_as_x=False, legacy_switch_as_x=True, name_prefix="Local ")
    _entity(
        env.ent_reg,
        entity_id="sensor.bad_unparsed",
        unique_id="corrupt_uid",
        platform=LEGACY_DOMAIN,
        config_entry=env.legacy_entry,
    )
    devices_before = {d.id: d for d in env.dev_reg.devices}
    entities_before = {e.entity_id: e for e in env.ent_reg.entities.values()}

    result = await async_migrate_from_legacy(hass, env.hub_entry, dry_run=True, cutover=True)

    assert result["success"] is True
    assert result["dry_run"] is True
    assert result["cutover"] is True
    assert _legacy_entries(hass) == [env.legacy_entry.entry_id]
    assert {d.id: d for d in env.dev_reg.devices} == devices_before
    assert {e.entity_id: e for e in env.ent_reg.entities.values()} == entities_before

    summary = result["summary"]
    assert summary["discovered_legacy_devices"] == 2
    assert summary["discovered_legacy_entities"] == 5
    assert summary["same_domain_entities"] == 4
    assert summary["domain_changed_entities"] == 1
    assert summary["skipped_entities"] == 1
    assert summary["conflicts"] == 0
    assert summary["legacy_entries_to_remove"] == 1

    assert result["domain_changed_entities"][0]["legacy_domain"] == "switch"
    assert result["domain_changed_entities"][0]["target_domain"] == "light"
    assert any("name_prefix" in w for w in result["warnings"])
    assert any("switch_as_x mismatch" in w for w in result["warnings"])
    assert any("freeathome_local_event" in w for w in result["warnings"])


async def test_side_by_side_metadata_sync(hass: HomeAssistant) -> None:
    """cutover=False transfers metadata and Assist options while preserving legacy."""
    env = _build_env(hass)

    result = await async_migrate_from_legacy(hass, env.hub_entry, dry_run=False, cutover=False)

    assert result["success"] is True
    assert _legacy_entries(hass) == [env.legacy_entry.entry_id]

    target_dev = env.dev_reg.async_get(env.devices["target_switch"])
    assert target_dev is not None
    assert target_dev.name_by_user == "Mein Bad Doppeltaster"
    assert target_dev.area_id == "bad"
    assert target_dev.labels == {"target", "licht", "bad"}

    target_sw = env.ent_reg.async_get("switch.target_bad_deckenlicht")
    assert target_sw is not None
    assert target_sw.name == "Deckenlicht Custom"
    assert target_sw.icon == "mdi:ceiling-light"
    assert target_sw.area_id == "bad"
    assert set(target_sw.aliases) == {"Bad Licht", COMPUTED_NAME}
    assert target_sw.labels == {"existing_target", "wichtig"}
    assert target_sw.options.get("conversation") == {"should_expose": True}
    assert target_sw.options.get("cloud.google_assistant") == {"should_expose": False}
    assert LEGACY_DOMAIN not in target_sw.options

    # User-only disablers/hiders are copied, integration ones are not; computed-only aliases skipped.
    target_dim = env.ent_reg.async_get("sensor.target_bad_dimming_status")
    assert target_dim is not None
    assert target_dim.disabled_by == RegistryEntryDisabler.USER
    assert target_dim.hidden_by == RegistryEntryHider.USER
    assert target_dim.aliases in ([], [COMPUTED_NAME])

    target_temp = env.ent_reg.async_get("sensor.target_bad_rt_temp")
    assert target_temp is not None
    assert target_temp.disabled_by is None
    assert target_temp.hidden_by is None
    assert target_temp.options.get("sensor") == {"display_precision": 2}
    assert target_temp.options.get("conversation") == {"should_expose": True}


async def test_full_cutover_preserves_entity_ids_and_helpers(hass: HomeAssistant) -> None:
    """cutover=True removes legacy, renames same-domain IDs, and handles conflicts."""
    env = _build_env(hass)
    _entity(
        env.ent_reg,
        entity_id="sensor.orphaned_co2",
        unique_id="orphan/ch0000/odp0001",
        platform=LEGACY_DOMAIN,
    )
    other_entry = MockConfigEntry(domain="other_integration")
    other_entry.add_to_hass(hass)

    orig_remove = hass.config_entries.async_remove

    async def _remove_with_reclaim(entry_id: str) -> Any:
        """Simulate a third-party entity reclaiming sensor.bad_rt_temp right after removal."""
        result = await orig_remove(entry_id)
        _entity(
            env.ent_reg,
            entity_id="sensor.bad_rt_temp",
            unique_id="other_rt_temp",
            platform="other_integration",
            config_entry=other_entry,
        )
        return result

    options_calls: list[str] = []
    orig_update_options = env.ent_reg.async_update_entity_options

    def _spy_update_options(entity_id: str, *args: Any, **kwargs: Any) -> Any:
        options_calls.append(entity_id)
        return orig_update_options(entity_id, *args, **kwargs)

    with (
        patch.object(hass.config_entries, "async_remove", _remove_with_reclaim),
        patch.object(env.ent_reg, "async_update_entity_options", _spy_update_options),
    ):
        result = await async_migrate_from_legacy(hass, env.hub_entry, dry_run=False, cutover=True)

    assert result["success"] is True
    assert _legacy_entries(hass) == []
    assert env.hub_entry.runtime_data.suppress_reload is False

    # Same-domain free@home Local entities now occupy the original legacy entity_ids.
    switch = env.ent_reg.async_get("switch.bad_deckenlicht")
    assert switch is not None and switch.platform == DOMAIN
    assert env.ent_reg.async_get("switch.target_bad_deckenlicht") is None

    scene = env.ent_reg.async_get("scene.abdunkeln")
    assert scene is not None and scene.platform == DOMAIN
    assert scene.options.get("conversation") == {"should_expose": True}

    # The reclaimed entity_id is a conflict: free@home Local keeps its id but still receives options.
    assert result["summary"]["conflicts"] == 1
    assert result["conflicts"][0]["entity_id"] == "sensor.bad_rt_temp"
    target_temp = env.ent_reg.async_get("sensor.target_bad_rt_temp")
    assert target_temp is not None
    assert target_temp.options.get("sensor") == {"display_precision": 2}

    # Options were written to the final entity_id, i.e. after the rename.
    assert "switch.bad_deckenlicht" in options_calls
    assert "switch.target_bad_deckenlicht" not in options_calls

    # Orphaned legacy entity removed; downstream helpers untouched.
    assert env.ent_reg.async_get("sensor.orphaned_co2") is None
    helper_light = env.ent_reg.async_get("light.bad_deckenlicht")
    assert helper_light is not None and helper_light.platform == "switch_as_x"
    helper_meter = env.ent_reg.async_get("sensor.bad_heizbedarf_heute")
    assert helper_meter is not None and helper_meter.platform == "utility_meter"


async def test_channel_ids_match_regardless_of_case(hass: HomeAssistant) -> None:
    """Legacy `ch001A` matches the SysAP's `ch001a`; the entity keeps its id and history."""
    env = _build_env(hass)
    _entity(
        env.ent_reg,
        entity_id="binary_sensor.door_call_3",
        unique_id="ABB700DA1DDF/ch001A",
        platform=LEGACY_DOMAIN,
        config_entry=env.legacy_entry,
    )
    _entity(
        env.ent_reg,
        entity_id="binary_sensor.target_door_call_3",
        unique_id=f"{SYSAP_UUID}/ABB700DA1DDF/ch001a",
        platform=DOMAIN,
        config_entry=env.hub_entry,
    )

    preview = await async_migrate_from_legacy(hass, env.hub_entry, dry_run=True, cutover=True)
    assert preview["missing_target_entities"] == []
    row = next(
        r
        for r in preview["entity_migrations"]
        if r["legacy_entity_id"] == "binary_sensor.door_call_3"
    )
    assert row["target_unique_id"] == f"{SYSAP_UUID}/ABB700DA1DDF/ch001a"
    assert row["history_preserved"] is True

    result = await async_migrate_from_legacy(hass, env.hub_entry, dry_run=False, cutover=True)
    assert result["missing_target_entities"] == []
    door_call = env.ent_reg.async_get("binary_sensor.door_call_3")
    assert door_call is not None and door_call.platform == DOMAIN


async def test_response_reports_missing_targets(hass: HomeAssistant) -> None:
    """Entities without a counterpart are reported under `missing_target_entities`."""
    env = _build_env(hass)
    env.ent_reg.async_remove("sensor.target_living_co2")

    preview = await async_migrate_from_legacy(hass, env.hub_entry, dry_run=True, cutover=True)
    assert len(preview["missing_target_entities"]) == 1
    assert preview["summary"]["missing_target_entities"] == 1
    row = preview["entity_migrations"][0]
    assert row["current_target_entity_id"] is not None

    result = await async_migrate_from_legacy(hass, env.hub_entry, dry_run=False, cutover=False)
    assert len(result["missing_target_entities"]) == 1
    assert result["summary"]["missing_target_entities"] == 1
    assert result["entity_migrations"][0]["current_target_entity_id"] is not None


async def test_cutover_keeps_switch_as_x_helper(hass: HomeAssistant) -> None:
    """A Switch-as-X helper on a legacy switch survives the cutover and wraps the new switch.

    Switch-as-X removes itself when its source entity is removed, so the migration
    unloads it before removing the legacy entities and sets it up again afterwards.
    """
    assert await async_setup_component(hass, "homeassistant", {})
    env = _build_env(hass)
    # Switch-as-X hides the switch it wraps.
    env.ent_reg.async_update_entity(
        "switch.bad_deckenlicht", hidden_by=er.RegistryEntryHider.INTEGRATION
    )
    helper = _switch_as_x(hass, "switch.bad_deckenlicht")
    assert await hass.config_entries.async_setup(helper.entry_id)
    await hass.async_block_till_done()
    options_before = dict(helper.options)

    preview = await async_migrate_from_legacy(hass, env.hub_entry, dry_run=True, cutover=True)
    assert helper.state is ConfigEntryState.LOADED
    assert dict(helper.options) == options_before
    assert preview["summary"]["helper_updates"] == 1
    assert preview["helper_updates"] == [
        {
            "config_entry_id": helper.entry_id,
            "domain": "switch_as_x",
            "title": "Deckenlicht",
            "legacy_entity_ids": ["switch.bad_deckenlicht"],
        }
    ]

    result = await async_migrate_from_legacy(hass, env.hub_entry, dry_run=False, cutover=True)
    await hass.async_block_till_done()

    assert result["summary"]["helper_updates"] == 1
    assert hass.config_entries.async_get_entry(helper.entry_id) is not None
    assert helper.state is ConfigEntryState.LOADED
    assert helper.options["entity_id"] == "switch.bad_deckenlicht"
    source = env.ent_reg.async_get("switch.bad_deckenlicht")
    assert source is not None and source.platform == DOMAIN
    assert source.hidden_by is er.RegistryEntryHider.INTEGRATION
    assert er.async_entries_for_config_entry(env.ent_reg, helper.entry_id)


class _StubFlow(ConfigFlow):
    """Config flow of the stub integrations below; never started."""

    VERSION = 1


@pytest.fixture
def stub_integrations(hass: HomeAssistant) -> Any:
    """Register the stub integrations `stubborn` (cannot unload) and `fragile` (fails to set up again)."""
    for domain, setup in (
        ("stubborn", AsyncMock(return_value=True)),
        ("fragile", AsyncMock(side_effect=[True, False])),
    ):
        mock_integration(
            hass,
            MockModule(
                domain,
                async_setup_entry=setup,
                async_unload_entry=AsyncMock(return_value=domain != "stubborn"),
            ),
        )
        mock_platform(hass, f"{domain}.config_flow", None)
    with patch.dict(HANDLERS, {"stubborn": _StubFlow, "fragile": _StubFlow}):
        yield


def _switch_as_x(hass: HomeAssistant, source: str) -> MockConfigEntry:
    """Add (not set up) a Switch-as-X helper wrapping `source` as a light."""
    helper = MockConfigEntry(
        domain="switch_as_x",
        title="Deckenlicht",
        options={"entity_id": source, "invert": False, "target_domain": "light"},
    )
    helper.add_to_hass(hass)
    return helper


async def test_loaded_helper_by_registry_id_follows_new_entity(hass: HomeAssistant) -> None:
    """A loaded helper referencing the legacy registry id ends up loaded on the new entity."""
    assert await async_setup_component(hass, "homeassistant", {})
    env = _build_env(hass)
    legacy = env.ent_reg.async_get("switch.bad_deckenlicht")
    target = env.ent_reg.async_get("switch.target_bad_deckenlicht")
    assert legacy is not None and target is not None
    helper = _switch_as_x(hass, legacy.id)
    assert await hass.config_entries.async_setup(helper.entry_id)
    await hass.async_block_till_done()

    result = await async_migrate_from_legacy(hass, env.hub_entry, dry_run=False, cutover=True)
    await hass.async_block_till_done()

    assert result["summary"]["helper_updates"] == 1
    assert helper.state is ConfigEntryState.LOADED
    assert helper.options["entity_id"] == target.id


@pytest.mark.usefixtures("stub_integrations")
async def test_cutover_aborts_when_a_helper_cannot_be_unloaded(hass: HomeAssistant) -> None:
    """If an entry using a legacy entity cannot be unloaded, nothing is removed or renamed."""
    assert await async_setup_component(hass, "homeassistant", {})
    env = _build_env(hass)
    helper = _switch_as_x(hass, "switch.bad_deckenlicht")
    assert await hass.config_entries.async_setup(helper.entry_id)
    stubborn = MockConfigEntry(
        domain="stubborn", title="Stur", options={"entity": "sensor.bad_rt_temp"}
    )
    stubborn.add_to_hass(hass)
    assert await hass.config_entries.async_setup(stubborn.entry_id)
    await hass.async_block_till_done()

    result = await async_migrate_from_legacy(hass, env.hub_entry, dry_run=False, cutover=True)
    await hass.async_block_till_done()

    assert result["success"] is False
    assert any("'Stur' (stubborn)" in w for w in result["warnings"])
    assert _legacy_entries(hass) == [env.legacy_entry.entry_id]
    assert env.ent_reg.async_get("switch.bad_deckenlicht").platform == LEGACY_DOMAIN
    assert helper.state is ConfigEntryState.LOADED


async def test_helpers_set_up_again_when_cutover_fails(hass: HomeAssistant) -> None:
    """An error during the cutover still sets the unloaded helpers up again."""
    assert await async_setup_component(hass, "homeassistant", {})
    env = _build_env(hass)
    helper = _switch_as_x(hass, "switch.bad_deckenlicht")
    assert await hass.config_entries.async_setup(helper.entry_id)
    await hass.async_block_till_done()

    with (
        patch(
            "custom_components.freeathome_local.migration._apply_entity_migration",
            side_effect=RuntimeError("boom"),
        ),
        pytest.raises(RuntimeError),
    ):
        await async_migrate_from_legacy(hass, env.hub_entry, dry_run=False, cutover=True)
    await hass.async_block_till_done()

    assert helper.state is ConfigEntryState.LOADED
    assert env.hub_entry.runtime_data.suppress_reload is False


@pytest.mark.usefixtures("stub_integrations")
async def test_helper_that_fails_to_set_up_again_is_reported(hass: HomeAssistant) -> None:
    """A helper that cannot be set up again after the cutover is named in a warning."""
    env = _build_env(hass)
    fragile = MockConfigEntry(
        domain="fragile", title="Zart", options={"entity": "sensor.bad_rt_temp"}
    )
    fragile.add_to_hass(hass)
    assert await hass.config_entries.async_setup(fragile.entry_id)

    result = await async_migrate_from_legacy(hass, env.hub_entry, dry_run=False, cutover=True)

    assert result["success"] is True
    assert any("'Zart' (fragile) could not be set up again" in w for w in result["warnings"])


async def test_helper_reference_by_registry_id_moves_to_new_entity(hass: HomeAssistant) -> None:
    """A helper option holding the legacy registry id is pointed at the new entity's id."""
    env = _build_env(hass)
    legacy = env.ent_reg.async_get("sensor.bad_rt_temp")
    target = env.ent_reg.async_get("sensor.target_bad_rt_temp")
    assert legacy is not None and target is not None
    helper = MockConfigEntry(
        domain="threshold",
        title="Bad zu kalt",
        options={"entity_id": legacy.id, "lower": 18.0, "hysteresis": 0.0, "name": "Bad zu kalt"},
    )
    helper.add_to_hass(hass)
    group_helper = MockConfigEntry(
        domain="min_max",
        title="Temperaturen",
        options={"entity_ids": [legacy.id, "sensor.outdoor"], "type": "mean"},
    )
    group_helper.add_to_hass(hass)

    result = await async_migrate_from_legacy(hass, env.hub_entry, dry_run=False, cutover=True)

    assert result["summary"]["helper_updates"] == 2
    assert helper.options["entity_id"] == target.id
    assert helper.options["lower"] == 18.0
    assert group_helper.options["entity_ids"] == [target.id, "sensor.outdoor"]


async def test_helper_on_entity_without_target_is_reported(hass: HomeAssistant) -> None:
    """A helper whose legacy entity has no free@home Local counterpart is named in a warning."""
    env = _build_env(hass)
    env.ent_reg.async_remove("sensor.target_living_co2")
    helper = MockConfigEntry(
        domain="derivative",
        title="CO2 Anstieg",
        options={"source": "sensor.living_co2", "name": "CO2 Anstieg", "round": 2},
    )
    helper.add_to_hass(hass)

    preview = await async_migrate_from_legacy(hass, env.hub_entry, dry_run=True, cutover=True)

    assert preview["summary"]["helper_updates"] == 0
    assert any("CO2 Anstieg" in w and "sensor.living_co2" in w for w in preview["warnings"])


async def test_cutover_aborts_safely_when_no_matching_target_entities(hass: HomeAssistant) -> None:
    """The legacy entry is never removed if zero free@home Local entities matched."""
    env = _build_env(hass)
    for entity in list(env.ent_reg.entities.values()):
        if entity.platform == DOMAIN:
            env.ent_reg.async_remove(entity.entity_id)

    result = await async_migrate_from_legacy(hass, env.hub_entry, dry_run=False, cutover=True)

    assert result["success"] is False
    assert _legacy_entries(hass) == [env.legacy_entry.entry_id]
    assert any("zero matching freeathome_local entities" in w for w in result["warnings"])


async def test_selective_serialnumbers_filter_and_partial_cutover_guard(
    hass: HomeAssistant,
) -> None:
    """The serialnumbers filter scopes dry_run/sync and rejects cutover=True."""
    env = _build_env(hass)

    preview = await async_migrate_from_legacy(
        hass,
        env.hub_entry,
        dry_run=True,
        cutover=False,
        serialnumbers_filter={"abb700da1ddf", "MISSING01"},
    )
    assert preview["summary"]["discovered_legacy_devices"] == 1
    assert preview["summary"]["discovered_legacy_entities"] == 2
    assert any("MISSING01" in w for w in preview["warnings"])

    synced = await async_migrate_from_legacy(
        hass,
        env.hub_entry,
        dry_run=False,
        cutover=False,
        serialnumbers_filter={"ABB700DA1DDF"},
    )
    assert synced["summary"]["same_domain_entities_migrated"] == 2
    assert env.dev_reg.async_get(env.devices["target_switch"]).area_id == "bad"
    assert env.dev_reg.async_get(env.devices["target_rt"]).area_id is None
    assert "sensor" not in env.ent_reg.async_get("sensor.target_bad_rt_temp").options

    with pytest.raises(ServiceValidationError) as exc:
        await async_migrate_from_legacy(
            hass,
            env.hub_entry,
            dry_run=False,
            cutover=True,
            serialnumbers_filter={"ABB700DA1DDF"},
        )
    assert exc.value.translation_domain == DOMAIN
    assert exc.value.translation_key == "partial_cutover_not_supported"
    assert _legacy_entries(hass) == [env.legacy_entry.entry_id]


async def test_migration_validation_errors_are_translated(hass: HomeAssistant) -> None:
    """Unloaded hubs and ambiguous legacy entries raise translated errors without writes."""
    unloaded = MockConfigEntry(domain=DOMAIN, unique_id="ABB700000009")
    unloaded.add_to_hass(hass)
    with pytest.raises(ServiceValidationError) as exc:
        await async_migrate_from_legacy(hass, unloaded, dry_run=True)
    assert exc.value.translation_key == "entry_not_loaded"
    assert exc.value.translation_placeholders == {"entry_id": unloaded.entry_id}

    env = _build_env(hass)
    hass.config_entries.async_update_entry(
        env.legacy_entry, unique_id="ABB700111111", data={CONF_HOST: "10.0.0.1"}
    )
    MockConfigEntry(
        domain=LEGACY_DOMAIN, unique_id="ABB700222222", data={CONF_HOST: "10.0.0.2"}
    ).add_to_hass(hass)
    with pytest.raises(ServiceValidationError) as exc:
        await async_migrate_from_legacy(hass, env.hub_entry, dry_run=False, cutover=True)
    assert exc.value.translation_key == "legacy_entry_ambiguous"
    assert len(_legacy_entries(hass)) == 2


async def test_device_metadata_updates_use_current_registry_api(hass: HomeAssistant) -> None:
    """Device metadata is transferred through the non-deprecated registry API.

    Calling the deprecated `async_get_device` from integration code raises in tests,
    so a successful run proves the modern lookup path is used.
    """
    env = _build_env(hass)
    result = await async_migrate_from_legacy(hass, env.hub_entry, dry_run=False, cutover=False)
    assert result["summary"]["device_metadata_updates"] == 2


async def test_migrate_service_multi_hub_and_legacy_flow_defaults(
    hass: HomeAssistant, init_integration: MockConfigEntry, mock_sysap: MockSysApServer
) -> None:
    """The service is registered with response support and disambiguates multiple hubs."""
    legacy_entry = MockConfigEntry(
        domain=LEGACY_DOMAIN,
        unique_id="ABB700999999",
        data={CONF_HOST: "192.168.8.23", "use_room_names": True, CONF_SWITCH_AS_X: False},
    )
    legacy_entry.add_to_hass(hass)
    # The legacy room-name option has no counterpart here and is not carried over.
    assert get_legacy_setup_defaults(hass) == {
        CONF_HOST: "192.168.8.23",
        CONF_SWITCH_AS_X: False,
    }
    assert hass.services.supports_response(DOMAIN, SERVICE_MIGRATE_FROM_LEGACY) == (
        SupportsResponse.ONLY
    )

    # A second loaded hub (another SysAP) makes an untargeted call ambiguous.
    other_config = {
        "11111111-1111-1111-1111-111111111111": next(iter(mock_sysap.configuration.values()))
    }
    other_sysap = MockSysApServer(port=0, serial_number="ABB700000002", configuration=other_config)
    await other_sysap.start()
    second = MockConfigEntry(
        domain=DOMAIN,
        unique_id="ABB700000002",
        data=entry_data(other_sysap, **{CONF_USERNAME: "apiuser", CONF_PASSWORD: "secret"}),
    )
    second.add_to_hass(hass)
    assert await hass.config_entries.async_setup(second.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_MIGRATE_FROM_LEGACY,
            {"dry_run": True},
            blocking=True,
            return_response=True,
        )

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_MIGRATE_FROM_LEGACY,
        {"config_entry_id": init_integration.entry_id, "dry_run": True},
        blocking=True,
        return_response=True,
    )
    assert response["success"] is True
    assert response["hub_entry_id"] == init_integration.entry_id

    assert await hass.config_entries.async_unload(second.entry_id)
    await other_sysap.stop()
