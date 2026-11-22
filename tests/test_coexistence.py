"""Tests verifying metadata integrity, localization parity, isolation, and diagnostics."""

from __future__ import annotations

import ast
import json
import os
import tomllib
from pathlib import Path
from types import SimpleNamespace

import yaml

from custom_components.freeathome_local import FreeAtHomeLocalRuntime
from custom_components.freeathome_local.api.client import FreeAtHomeLocalApiClient
from custom_components.freeathome_local.api.controller import FreeAtHomeController
from custom_components.freeathome_local.const import (
    DOMAIN,
    EVENT_FREEATHOME_LOCAL,
    EVENT_SCENE_TRIGGERED,
    EVENT_VIRTUAL_DEVICE_COMMAND,
)
from custom_components.freeathome_local.device_layout import (
    channel_identifier,
    hub_identifier,
    physical_identifier,
)
from custom_components.freeathome_local.diagnostics import (
    async_get_config_entry_diagnostics,
    async_get_device_diagnostics,
)
from custom_components.freeathome_local.fah_event import (
    DIMMING_STATUS_DEFAULT,
    create_event_data,
    dimming_status_sequence_from_event,
)
from custom_components.freeathome_local.sensor import SENSOR_TYPES

ROOT_DIR = Path(__file__).resolve().parent.parent
COMP_DIR = ROOT_DIR / "custom_components" / "freeathome_local"
FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "configuration.json"


def _collect_nested_keys(mapping: dict, prefix: str = "") -> set[str]:
    """Return dotted key paths for every nested dict in a translation file."""
    keys: set[str] = set()
    for key, value in mapping.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        keys.add(path)
        if isinstance(value, dict):
            keys |= _collect_nested_keys(value, path)
    return keys


def test_manifest_and_hacs_metadata() -> None:
    """Verify manifest.json, pyproject.toml, hacs.json, and brand PNGs follow standards."""
    manifest = json.loads((COMP_DIR / "manifest.json").read_text(encoding="utf-8"))
    hacs = json.loads((ROOT_DIR / "hacs.json").read_text(encoding="utf-8"))
    pyproject = tomllib.loads((ROOT_DIR / "pyproject.toml").read_text(encoding="utf-8"))

    assert manifest["domain"] == "freeathome_local"
    assert list(manifest.keys()) == [
        "domain",
        "name",
        *sorted(k for k in manifest if k not in ("domain", "name")),
    ]
    assert manifest["integration_type"] == "hub"
    assert manifest["categories"] == ["hubs_protocols"]
    assert manifest["requirements"] == []
    assert manifest["iot_class"] == "local_push"
    assert manifest["config_flow"] is True
    assert manifest["version"] == pyproject["project"]["version"]
    assert hacs["render_readme"] is True
    assert hacs["homeassistant"] == "2026.9.0"

    for png in ("icon.png", "icon@2x.png", "logo.png", "logo@2x.png"):
        path = COMP_DIR / "brand" / png
        assert path.is_file()
        assert path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_translations_and_services_yaml_valid() -> None:
    """Ensure strings.json, all 7 translations, and services.yaml are valid and in sync."""
    services = yaml.safe_load((COMP_DIR / "services.yaml").read_text(encoding="utf-8"))
    for expected in (
        "dump_config",
        "monitor",
        "set_datapoint",
        "register_virtual_device",
        "unregister_virtual_device",
        "trigger_proxy_device",
        "send_notification",
        "migrate_from_legacy",
    ):
        assert expected in services

    strings_data = json.loads((COMP_DIR / "strings.json").read_text(encoding="utf-8"))
    expected_keys = _collect_nested_keys(strings_data)

    for rel in (
        "strings.json",
        "translations/en.json",
        "translations/de.json",
        "translations/nl.json",
        "translations/fr.json",
        "translations/it.json",
        "translations/es.json",
        "translations/pl.json",
    ):
        data = json.loads((COMP_DIR / rel).read_text(encoding="utf-8"))
        assert _collect_nested_keys(data) == expected_keys, f"Key mismatch in {rel}"
        assert "config" in data
        assert "options" in data
        assert "entity" in data
        assert "services" in data

        sensor_trans = data["entity"]["sensor"]
        # ADR-001: entity names never repeat the channel name, which comes from the
        # channel device, so translations carry no name placeholders.
        for sensor_type in (*SENSOR_TYPES, "dimming_status", "thermostat_temperature"):
            assert sensor_type in sensor_trans
            assert "{" not in sensor_trans[sensor_type]["name"]

        for svc_name, svc_def in services.items():
            assert svc_name in data["services"]
            for field_name in svc_def.get("fields", {}):
                assert field_name in data["services"][svc_name]["fields"]


def test_api_layer_has_no_homeassistant_imports() -> None:
    """Keep api/ pure Python: no homeassistant imports and no imports from the HA layer."""
    api_dir = COMP_DIR / "api"
    for py_file in api_dir.rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        # How many package levels `py_file` sits below `api/` (0 for api/*.py).
        depth = len(py_file.relative_to(api_dir).parts) - 1
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("homeassistant"), py_file
                    assert not alias.name.startswith("custom_components"), py_file
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert not module.startswith(("homeassistant", "custom_components")), py_file
                # A relative import may not climb out of api/ into the HA layer.
                assert node.level <= depth + 1, f"{py_file} imports from outside api/"


def test_agents_and_readme_governance() -> None:
    """Verify AGENTS.md size limits, standards docs, and clean README/CHANGELOG."""
    agents_path = ROOT_DIR / "AGENTS.md"
    assert agents_path.is_file()
    agents_text = agents_path.read_text(encoding="utf-8")
    assert len(agents_text.splitlines()) <= 200
    assert len(agents_text) <= 16000

    assert (ROOT_DIR / "docs" / "HA_INTEGRATION_STANDARDS.md").is_file()
    assert (ROOT_DIR / "docs" / "MIGRATION.md").is_file()

    readme_text = (ROOT_DIR / "README.md").read_text(encoding="utf-8")
    changelog_text = (ROOT_DIR / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "Marketplace" in readme_text
    assert "jheling" not in readme_text.lower()
    assert "Credits & Acknowledgments" not in readme_text
    assert "jheling" not in changelog_text.lower()
    assert os.path.isdir(COMP_DIR)


async def test_no_collision_with_legacy_freeathome_integration() -> None:
    """Ensure domain, device identifiers, unique IDs, and events never collide with `freeathome`."""
    assert DOMAIN != "freeathome"
    assert EVENT_FREEATHOME_LOCAL != "freeathome_event"
    assert EVENT_SCENE_TRIGGERED != "freeathome_event"
    assert EVENT_VIRTUAL_DEVICE_COMMAND != "freeathome_event"

    config = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    client = FreeAtHomeLocalApiClient("192.168.1.50", "apiuser", "secret")
    controller = FreeAtHomeController(client)
    try:
        controller.load_configuration(config)
        seen_unique_ids: set[str] = set()
        for dev in controller.devices:
            for id_domain, id_value in (
                physical_identifier(dev),
                channel_identifier(dev),
                hub_identifier("entry_1"),
            ):
                assert id_domain == "freeathome_local"
                assert id_domain != "freeathome"
                assert id_value

            assert dev.unique_id not in seen_unique_ids
            seen_unique_ids.add(dev.unique_id)
    finally:
        await controller.close()


def test_all_platforms_and_config_flow_import() -> None:
    """Verify all integration modules import cleanly without syntax/import errors."""
    import importlib

    for module_name in (
        "custom_components.freeathome_local",
        "custom_components.freeathome_local.config_flow",
        "custom_components.freeathome_local.diagnostics",
        "custom_components.freeathome_local.entity",
        "custom_components.freeathome_local.migration",
        "custom_components.freeathome_local.light",
        "custom_components.freeathome_local.switch",
        "custom_components.freeathome_local.cover",
        "custom_components.freeathome_local.climate",
        "custom_components.freeathome_local.fan",
        "custom_components.freeathome_local.sensor",
        "custom_components.freeathome_local.binary_sensor",
        "custom_components.freeathome_local.button",
        "custom_components.freeathome_local.lock",
        "custom_components.freeathome_local.scene",
    ):
        mod = importlib.import_module(module_name)
        assert mod is not None


async def test_diagnostics_redacts_secrets() -> None:
    """Verify entry and device diagnostics redact credentials and scope telemetry."""
    config = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    client = FreeAtHomeLocalApiClient("192.168.1.50", "secret_user", "super_secret_pw")
    controller = FreeAtHomeController(client)
    controller.sysap_serial = "ABB700SECRET"
    controller.load_configuration(config)

    entry = SimpleNamespace(
        entry_id="entry_1",
        title="Test SysAP",
        data={
            "host": "192.168.1.50",
            "username": "secret_user",
            "password": "super_secret_pw",
        },
        options={"name_prefix": "Local "},
        runtime_data=None,
    )
    entry.runtime_data = FreeAtHomeLocalRuntime(controller=controller, entry=entry)
    hass = SimpleNamespace()
    try:
        diag = await async_get_config_entry_diagnostics(hass, entry)  # type: ignore[arg-type]
        assert diag["entry"]["data"]["password"] == "**REDACTED**"
        assert diag["entry"]["data"]["username"] == "**REDACTED**"
        assert diag["controller"]["sysap_serial"] == "**REDACTED**"
        assert diag["controller"]["host"] == "**REDACTED**"
        assert diag["entry"]["data"]["host"] == "**REDACTED**"
        assert diag["entry"]["title"] == "**REDACTED**"
        assert diag["controller"]["total_devices"] == len(controller.devices)
        text = json.dumps(diag)
        for secret in ("192.168.1.50", "Test SysAP", controller.primary_sysap_uuid, "ABB700D10001"):
            assert secret not in text
        assert "Living Switch" in text  # names stay, so reports match the user's UI
        virtual = [
            s for s in config[controller.primary_sysap_uuid]["devices"] if s.startswith("6000")
        ]
        assert virtual
        assert all(serial in text for serial in virtual)  # needed to address virtual devices

        sysap_uuid = controller.primary_sysap_uuid
        dev_diag = await async_get_device_diagnostics(
            hass,  # type: ignore[arg-type]
            entry,  # type: ignore[arg-type]
            SimpleNamespace(identifiers={(DOMAIN, f"{sysap_uuid}_ABB700D10001")}),
        )
        assert dev_diag["device"]["serialnumber"].startswith("ABB7")
        assert dev_diag["device"]["serialnumber"] != "ABB700D10001"
        assert dev_diag["device"]["sysap_uuid"] != sysap_uuid
        assert dev_diag["device"]["model"] == "Sensor/switch actuator 1/1-gang"
        assert len(dev_diag["channels"]) == 2
        assert dev_diag["raw_device_config"]["displayName"] == "Living Switch"

        hub_diag = await async_get_device_diagnostics(
            hass,  # type: ignore[arg-type]
            entry,  # type: ignore[arg-type]
            SimpleNamespace(identifiers={(DOMAIN, "hub_entry_1")}),
        )
        assert hub_diag["controller"]["total_devices"] == len(controller.devices)

        unloaded_entry = SimpleNamespace(
            entry_id="entry_2",
            title="Unloaded SysAP",
            data={"host": "192.168.1.51", "username": "u", "password": "pw"},
            options={},
            runtime_data=None,
        )
        unloaded_diag = await async_get_config_entry_diagnostics(
            hass,  # type: ignore[arg-type]
            unloaded_entry,  # type: ignore[arg-type]
        )
        assert unloaded_diag["status"] == "not_loaded"
        assert unloaded_diag["entry"]["data"]["password"] == "**REDACTED**"

        unloaded_dev_diag = await async_get_device_diagnostics(
            hass,  # type: ignore[arg-type]
            unloaded_entry,  # type: ignore[arg-type]
            SimpleNamespace(identifiers={(DOMAIN, f"{sysap_uuid}_ABB700D10001")}),
        )
        assert unloaded_dev_diag["status"] == "not_loaded"
    finally:
        await controller.close()


def test_fah_event_helpers() -> None:
    """Verify event data builder and dimming status sequences."""
    ev = {"command": "dim_start", "direction": "up"}
    payload = create_event_data("Rocker", "ABB1", "uid1", ev)
    assert payload == {
        "name": "Rocker",
        "serialnumber": "ABB1",
        "unique_id": "uid1",
        "command": "dim_start",
        "direction": "up",
    }
    assert dimming_status_sequence_from_event(ev) == ("held_up",)
    assert dimming_status_sequence_from_event({"command": "pressed", "state": False}) == (
        "pressed_down",
        DIMMING_STATUS_DEFAULT,
    )
    assert dimming_status_sequence_from_event({"command": "dim_stop", "direction": "down"}) == (
        DIMMING_STATUS_DEFAULT,
    )


def test_icons_json_matches_translations_and_services() -> None:
    """Every icon translation targets a known entity translation key or service."""
    icons = json.loads((COMP_DIR / "icons.json").read_text(encoding="utf-8"))
    strings = json.loads((COMP_DIR / "strings.json").read_text(encoding="utf-8"))
    for platform, keys in icons["entity"].items():
        for key, spec in keys.items():
            assert key in strings["entity"][platform], f"{platform}.{key} has no translation"
            assert spec["default"].startswith("mdi:")
            for state in spec.get("state", {}):
                assert state in strings["entity"][platform][key]["state"]
    services = yaml.safe_load((COMP_DIR / "services.yaml").read_text(encoding="utf-8"))
    assert set(icons["services"]) == set(services)
