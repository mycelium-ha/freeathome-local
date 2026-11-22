"""Edge cases of the configuration model and WebSocket frame routing."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock

import pytest

from custom_components.freeathome_local.api.client import (
    FreeAtHomeAuthError,
    FreeAtHomeLocalApiClient,
)
from custom_components.freeathome_local.api.controller import FreeAtHomeController

from .test_controller_and_devices import SYSAP_UUID, _make_controller

MESSY_CONFIG: dict[str, Any] = {
    "not-a-sysap": "junk",
    SYSAP_UUID: {
        "sysapName": " Messy ",
        "floorplan": {
            "floors": {
                "00": "junk",
                "01": {"name": "Ground", "rooms": {"01": {"name": " Hall "}, "02": "junk"}},
            }
        },
        "devices": {
            "JUNK": "junk",
            "NOCHANNELS": {"displayName": "Empty", "channels": {}},
            "ABB700E00001": {
                # No room on the device, but its only assigned channel is in the hall.
                "displayName": "Hall Actuator",
                "deviceId": "unknown-model",
                "softwareVersion": "1.2.3",
                "channels": {
                    "ch0000": "junk",
                    "ch0001": {"displayName": "No Function"},
                    "ch0002": {
                        "displayName": "Hall Actuator Lamp",
                        "functionID": "0012",
                        "floor": "01",
                        "room": "01",
                        "inputs": {
                            "idp0000": {"pairingID": 1, "value": "0"},
                            "idp0001": {"pairingID": 17, "value": ""},
                            "junk": "junk",
                        },
                        "outputs": {
                            "odp0000": {"pairingID": 256, "value": "1"},
                            "odp0001": {"pairingID": 272, "value": "40"},
                        },
                    },
                },
            },
            "ABB700E00002": {
                "displayName": "Hall Rocker",
                "floor": "01",
                "room": "01",
                "channels": {
                    "ch0000": {
                        "displayName": "Hall Rocker rocker",
                        "functionID": "0012",
                        "sameLocation": True,
                        "floor": "99",
                        "inputs": {"idp0000": {"pairingID": 1}},
                        "outputs": {"odp0000": {"pairingID": 256, "value": "0"}},
                    }
                },
            },
        },
    },
}


def _messy_controller(**kwargs: Any) -> FreeAtHomeController:
    client = FreeAtHomeLocalApiClient("192.168.1.50", "apiuser", "secret")
    client.set_datapoint = AsyncMock(return_value={})  # type: ignore[method-assign]
    client.get_device = AsyncMock(return_value={})  # type: ignore[method-assign]
    controller = FreeAtHomeController(client, **kwargs)
    controller.load_configuration(MESSY_CONFIG)
    return controller


def _frame(**sections: Any) -> dict[str, Any]:
    return {SYSAP_UUID: sections}


async def test_messy_configuration_is_parsed_defensively() -> None:
    """Junk entries are skipped; the device area falls back to its channels' room."""
    ctrl = _messy_controller()
    try:
        assert ctrl.sysap_uuids == [SYSAP_UUID]
        assert ctrl.sysap_names[SYSAP_UUID] == "Messy"
        lamp = next(d for d in ctrl.devices if d.serialnumber == "ABB700E00001")
        assert lamp.channel_id == "ch0002"
        assert lamp.device_info["suggested_area"] == "Hall"
        assert lamp.device_info["sw_version"] == "1.2.3"
        assert lamp.device_info["model"] == "unknown-model"
        assert lamp.name == "Lamp"
        assert lamp.room_name == "Hall"
        rocker = next(d for d in ctrl.devices if d.serialnumber == "ABB700E00002")
        assert rocker.name == "Hall Rocker"
        assert ctrl.configured_device_keys() >= {
            f"{SYSAP_UUID}_JUNK",
            f"{SYSAP_UUID}_NOCHANNELS",
            f"{SYSAP_UUID}_ABB700E00001_ch0002",
        }
    finally:
        await ctrl.close()


async def test_ws_frames_with_junk_are_ignored() -> None:
    """Malformed frames, paths and values neither crash nor change state."""
    ctrl = _messy_controller()
    lamp = next(d for d in ctrl.devices if d.serialnumber == "ABB700E00001")
    seen: list[dict[str, Any]] = []

    def _broken_listener(_payload: dict[str, Any]) -> None:
        raise RuntimeError("listener bug")

    ctrl.add_ws_frame_listener(_broken_listener)
    ctrl.add_ws_frame_listener(_broken_listener)
    ctrl.add_ws_frame_listener(seen.append)
    try:
        await ctrl.handle_ws_message({"other": "junk"})
        await ctrl.handle_ws_message(
            _frame(
                datapoints={
                    "ABB700E00001/ch0002/odp0001": None,
                    "too/short": "1",
                    "ABB700E00001/ch0002/odp0000": "0",
                },
                parameters={
                    "ABB700E00001/ch0002/par0001": None,
                    "bad": "1",
                    "ABB700E00001/ch0002/par0002": {"value": "5"},
                },
                devicesRemoved=["UNKNOWN"],
            )
        )
        assert lamp.state is False  # type: ignore[attr-defined]
        assert len(seen) == 2
    finally:
        ctrl.remove_ws_frame_listener(_broken_listener)
        ctrl.remove_ws_frame_listener(_broken_listener)
        await ctrl.close()


async def test_devices_added_fetch_variants(caplog: pytest.LogCaptureFixture) -> None:
    """Added devices are fetched in either response shape; fetch errors are logged."""
    ctrl = _messy_controller()
    added: list[list[Any]] = []

    async def _on_added(devices: list[Any]) -> None:
        added.append(devices)

    ctrl.register_devices_added_cb(_on_added)
    ctrl.register_devices_added_cb(_on_added)
    new_device = {
        "displayName": "New",
        "floor": "01",
        "room": "01",
        "channels": {
            "ch0000": {
                "functionID": "0007",
                "inputs": {"idp0000": {"pairingID": 1}},
                "outputs": {"odp0000": {"pairingID": 256, "value": "1"}},
            }
        },
    }
    ctrl.client.get_device = AsyncMock(  # type: ignore[method-assign]
        side_effect=[{"ABB700E00010": new_device}, RuntimeError("offline"), {"x": "junk"}]
    )
    caplog.set_level(logging.DEBUG)
    try:
        await ctrl.handle_ws_message(
            _frame(devicesAdded=["ABB700E00010", "ABB700E00011", "ABB700E00012"])
        )
        assert len(added) == 1
        assert added[0][0].serialnumber == "ABB700E00010"
        assert "Could not fetch added device ABB700E00011" in caplog.text

        # Re-announcing a known device creates nothing new.
        await ctrl.handle_ws_message(_frame(devices={"ABB700E00010": new_device}))
        assert len(added) == 1
    finally:
        await ctrl.close()


async def test_virtual_device_feedback_write_failure_is_tolerated(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failing feedback write is logged and the command callback still runs."""
    ctrl = _make_controller()
    ctrl.client.set_datapoint = AsyncMock(  # type: ignore[method-assign]
        side_effect=RuntimeError("write failed")
    )
    commands: list[tuple[str, ...]] = []

    async def _on_command(*args: str) -> None:
        commands.append(args)

    ctrl.register_virtual_device_command_cb(_on_command)
    ctrl.register_virtual_device_command_cb(_on_command)
    caplog.set_level(logging.DEBUG)
    try:
        await ctrl.handle_ws_message(
            _frame(
                datapoints={"6000A1B2C3D4/ch0000/idp0000": "1", "6000A1B2C3D4/ch0000/idp0009": "1"}
            )
        )
        relay = next(d for d in ctrl.devices if d.serialnumber == "6000A1B2C3D4")
        assert relay.state is True  # type: ignore[attr-defined]
        assert "Virtual device feedback write failed" in caplog.text
        assert len(commands) == 2
    finally:
        await ctrl.close()


async def test_resync_skips_junk_and_updates_parameters() -> None:
    """A resync applies datapoint and parameter values and skips junk entries."""
    ctrl = _make_controller()
    tunable = next(
        d for d in ctrl.devices if d.serialnumber == "ABB700D10002" and d.channel_id == "ch0001"
    )
    param_id = next(iter(tunable._parameters.values()))
    ctrl.client.get_configuration = AsyncMock(  # type: ignore[method-assign]
        return_value={
            "junk": "junk",
            SYSAP_UUID: {
                "devices": {
                    "JUNK": "junk",
                    "ABB700D10002": {
                        "channels": {
                            "ch0000": "junk",
                            "ch0001": {
                                "outputs": {"odp0000": "junk", "odp0001": {"value": ""}},
                                "parameters": {param_id: "3000", "par9999": None},
                            },
                        }
                    },
                }
            },
        }
    )
    try:
        await ctrl.resync_configuration()
        assert 3000 in (tunable.min_color_temp, tunable.max_color_temp)  # type: ignore[attr-defined]
    finally:
        await ctrl.close()


def test_connection_state_outside_event_loop() -> None:
    """Connection changes without a running loop only update the flag."""
    client = FreeAtHomeLocalApiClient("192.168.1.50", "apiuser", "secret")
    ctrl = FreeAtHomeController(client)
    ctrl._on_connection_state(True)
    ctrl._on_connection_state(False)
    assert ctrl.ws_connected is False
    assert not ctrl._pending_tasks


async def test_validate_connection_and_auth_fallback() -> None:
    """Empty configurations are rejected; failed fallbacks restore the user name."""
    client = FreeAtHomeLocalApiClient("sysap.local", "Installer", "secret")
    client.fetch_settings_json = AsyncMock(  # type: ignore[method-assign]
        return_value={"users": [{"name": "Installer", "jid": "abc@busch-jaeger.de"}]}
    )
    client.get_configuration = AsyncMock(return_value={})  # type: ignore[method-assign]
    ctrl = FreeAtHomeController(client)
    with pytest.raises(FreeAtHomeAuthError):
        await ctrl.validate_connection()

    client.get_configuration = AsyncMock(  # type: ignore[method-assign]
        return_value={SYSAP_UUID: "junk"}
    )
    assert await ctrl.validate_connection() == "sysap.local"

    client.get_configuration = AsyncMock(  # type: ignore[method-assign]
        side_effect=FreeAtHomeAuthError("denied")
    )
    with pytest.raises(FreeAtHomeAuthError):
        await ctrl.validate_connection()
    assert client.get_configuration.await_count == 3
    assert client.username == "Installer"
    await ctrl.close()
