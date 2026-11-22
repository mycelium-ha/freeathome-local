"""`scripts/anonymize_dump.py`: dumps become fixtures without personal data."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from mock_sysap_server import MockSysApServer
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.freeathome_local.const import DOMAIN

from .conftest import TESTS_DIR

_SPEC = importlib.util.spec_from_file_location(
    "anonymize_dump", TESTS_DIR.parent / "scripts" / "anonymize_dump.py"
)
assert _SPEC is not None and _SPEC.loader is not None
anonymize_dump = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(anonymize_dump)

FIXTURE = json.loads((TESTS_DIR / "fixtures" / "configuration.json").read_text(encoding="utf-8"))
REAL_UUID = "3f2a9c1e-1111-4abc-9def-0123456789ab"


def _real_dump() -> dict[str, Any]:
    """Return the fixture dressed up like a real dump with personal data."""
    sysap = copy.deepcopy(next(iter(FIXTURE.values())))
    sysap["sysapName"] = "Haus Mustermann"
    sysap["users"] = {"1": {"jid": "a@busch-jaeger.de", "name": "Max", "role": "admin"}}
    sysap["location"] = {"latitude": 48.1, "longitude": 11.5}
    device = sysap["devices"]["ABB700D10001"]
    device["displayName"] = "Wohnzimmer Schalter"
    device["hostAddress"] = "192.168.1.20"
    device["channels"]["ch0000"]["outputs"]["odp0000"]["value"] = "mail me@home.example now"
    return {REAL_UUID: sysap}


def test_anonymize_replaces_identifying_data() -> None:
    """UUIDs, serials, names, accounts, network and location data are replaced."""
    anonymizer = anonymize_dump.Anonymizer()
    result = anonymizer.run(_real_dump())
    text = json.dumps(result)

    assert list(result) == ["00000000-0000-0000-0000-000000000001"]
    for secret in (REAL_UUID, "Mustermann", "busch-jaeger", "192.168.1.20", "me@home", "48.1"):
        assert secret not in text
    sysap = result["00000000-0000-0000-0000-000000000001"]
    assert {"users", "location"}.isdisjoint(sysap)
    assert sysap["sysapName"] == "SysAP"
    assert "ABB700D10001" not in sysap["devices"]
    assert {"users", "location", "hostAddress"} <= anonymizer.removed_keys
    assert anonymizer.scrubbed_values == 1

    first = sysap["devices"][anonymizer.serial("ABB700D10001")]
    assert first["displayName"] == "Device 1"
    assert first["channels"]["ch0000"]["displayName"] == "Channel 1.1"
    rooms = sysap["floorplan"]["floors"]["01"]["rooms"]
    assert rooms["01"]["name"] == "Room 01.01"


def test_anonymize_keeps_protocol_data_and_prefixes() -> None:
    """Function, pairing and parameter IDs survive; serial prefixes keep the device type."""
    anonymizer = anonymize_dump.Anonymizer(keep_names=True)
    result = anonymizer.run(copy.deepcopy(FIXTURE))
    original = next(iter(FIXTURE.values()))["devices"]
    devices = next(iter(result.values()))["devices"]
    for serial, device in original.items():
        new_serial = anonymizer.serial(serial)
        assert new_serial[:4] == serial[:4]
        if serial.startswith("FFFF"):
            assert new_serial[:8] == serial[:8]
        assert devices[new_serial]["displayName"] == device["displayName"]
        for channel_id, channel in device.get("channels", {}).items():
            new_channel = devices[new_serial]["channels"][channel_id]
            assert new_channel.get("functionID") == channel.get("functionID")
            assert new_channel.get("inputs") == channel.get("inputs")
            assert new_channel.get("outputs") == channel.get("outputs")
            assert new_channel.get("parameters") == channel.get("parameters")


def test_anonymize_command_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The script writes the anonymised dump and reports what it changed."""
    source = tmp_path / "dump.json"
    source.write_text(json.dumps(_real_dump()), encoding="utf-8")
    target = tmp_path / "fixture.json"
    assert anonymize_dump.main([str(source), "-o", str(target)]) == 0
    assert "Mustermann" not in target.read_text(encoding="utf-8")
    assert "Review the result" in capsys.readouterr().err

    assert anonymize_dump.main([str(source)]) == 0
    assert json.loads(capsys.readouterr().out)


async def test_anonymized_fixture_sets_up_the_same_entities(
    hass: HomeAssistant, mock_sysap: MockSysApServer, mock_config_entry: MockConfigEntry
) -> None:
    """An anonymised dump yields the same entities, so it can reproduce bugs."""
    registry = er.async_get(hass)

    async def _entities(entry: MockConfigEntry) -> list[tuple[str, str]]:
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        found = [
            (e.domain, e.unique_id.split("/", 1)[1])
            for e in er.async_entries_for_config_entry(registry, entry.entry_id)
        ]
        assert await hass.config_entries.async_remove(entry.entry_id)
        await hass.async_block_till_done()
        return found

    original = await _entities(mock_config_entry)
    anonymizer = anonymize_dump.Anonymizer()
    mock_sysap.configuration = anonymizer.run(copy.deepcopy(FIXTURE))
    anonymized = await _entities(
        MockConfigEntry(domain=DOMAIN, unique_id="anonymized", data=dict(mock_config_entry.data))
    )

    def _map(unique_tail: str) -> str:
        serial, rest = unique_tail.split("/", 1)
        return f"{anonymizer.serial(serial)}/{rest}"

    assert original
    assert sorted(anonymized) == sorted((domain, _map(tail)) for domain, tail in original)


def test_anonymize_reads_diagnostics_download(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A diagnostics download is unwrapped to its configuration before anonymising."""
    source = tmp_path / "diagnostics.json"
    source.write_text(
        json.dumps({"home_assistant": {}, "data": {"raw_configuration": _real_dump()}}),
        encoding="utf-8",
    )
    assert anonymize_dump.main([str(source)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert list(result) == ["00000000-0000-0000-0000-000000000001"]


def test_anonymize_tolerates_unexpected_shapes() -> None:
    """Unexpected value types are passed through instead of failing."""
    dump = {
        "not-a-uuid": "text",
        REAL_UUID: {
            "devices": {"ABB700000009": "broken", "ABB70000000A": {"channels": {"ch0000": 1}}},
            "floorplan": {"floors": {"01": "broken", "02": {"name": "x", "rooms": {"01": 2}}}},
            "list": [{"password": "x"}, "192.168.0.1"],
        },
    }
    result = anonymize_dump.Anonymizer().run(dump)
    sysap = result["00000000-0000-0000-0000-000000000001"]
    assert result["not-a-uuid"] == "text"
    assert list(sysap["devices"].values())[0] == "broken"
    assert sysap["floorplan"]["floors"]["01"] == "broken"
    assert sysap["floorplan"]["floors"]["02"]["rooms"]["01"] == 2
    assert sysap["list"] == [{}, "192.0.2.1"]
