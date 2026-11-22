"""Edge cases of the HA entities that the end-to-end platform tests do not reach."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.climate import ClimateEntityFeature, HVACMode
from homeassistant.components.cover import CoverDeviceClass, CoverEntityFeature
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from mock_sysap_server import MockSysApServer
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.freeathome_local.api.const import (
    FUNCTION_IDS_ATTIC_WINDOW_ACTUATOR,
    FUNCTION_IDS_AWNING_ACTUATOR,
    FUNCTION_IDS_CONTROL_ELEMENT,
    FUNCTION_IDS_DOOR_CALL_SENSOR,
    FUNCTION_IDS_DOOR_OPENER,
    PID_CONTROLLER_ON_OFF,
    PID_CONTROLLER_ON_OFF_REQUEST,
    PID_FAN_STAGE_REQUEST,
    PID_MEASURED_BRIGHTNESS,
    PID_MOVE_UP_DOWN,
    PID_OUTDOOR_TEMPERATURE,
    PID_SWITCH_ON_OFF,
    PID_WIND_SPEED,
)
from custom_components.freeathome_local.api.devices import (
    FahBinarySensor,
    FahCover,
    FahLight,
    FahLock,
    FahSensor,
    FahThermostat,
)
from custom_components.freeathome_local.api.devices.base import FahBaseDevice
from custom_components.freeathome_local.binary_sensor import FreeAtHomeLocalBinarySensor
from custom_components.freeathome_local.climate import FreeAtHomeLocalThermostat
from custom_components.freeathome_local.const import DOMAIN
from custom_components.freeathome_local.cover import FreeAtHomeLocalCover
from custom_components.freeathome_local.event import FreeAtHomeLocalControlEvent
from custom_components.freeathome_local.fah_event import HOLD_EVENT_TYPES, PRESS_EVENT_TYPES
from custom_components.freeathome_local.lock import FreeAtHomeLocalLock
from custom_components.freeathome_local.sensor import FreeAtHomeLocalSensor, _build_sensor_entities

from .conftest import SYSAP_UUID


def _make[T: FahBaseDevice](
    cls: type[T], datapoints: dict[int, str], *, function_id: int | None = None
) -> T:
    controller: Any = MagicMock()
    controller.set_datapoint = AsyncMock()
    controller.set_parameter = AsyncMock()
    return cls(
        controller,
        {"identifiers": set()},
        "ABB700D10099",
        "ch0000",
        function_id,
        "Test",
        datapoints=datapoints,
        sysap_uuid="uuid",
    )


def _written(device: FahBaseDevice) -> list[tuple[str, str]]:
    return [(c.args[2], c.args[3]) for c in device.controller.set_datapoint.await_args_list]


async def test_thermostat_without_demand_or_fan() -> None:
    """No valve value means no HVAC action; no fan datapoint means no fan mode."""
    device = _make(FahThermostat, {PID_CONTROLLER_ON_OFF: "odp0000"})
    device.update_datapoint("odp0000", "1")
    thermostat = FreeAtHomeLocalThermostat(device)
    assert thermostat.hvac_mode == HVACMode.HEAT
    assert thermostat.hvac_action is None
    assert thermostat.fan_mode is None
    assert not thermostat.supported_features & ClimateEntityFeature.FAN_MODE


async def test_thermostat_ignores_unsupported_requests() -> None:
    """Unsupported HVAC modes and calls without a temperature write nothing."""
    device = _make(
        FahThermostat,
        {PID_CONTROLLER_ON_OFF_REQUEST: "idp0000", PID_FAN_STAGE_REQUEST: "idp0001"},
    )
    thermostat = FreeAtHomeLocalThermostat(device)
    await thermostat.async_set_hvac_mode(HVACMode.AUTO)
    await thermostat.async_set_temperature()
    assert _written(device) == []
    await thermostat.async_set_fan_mode("high")
    assert _written(device) == [("idp0001", "3")]
    assert thermostat.supported_features & ClimateEntityFeature.FAN_MODE


@pytest.mark.parametrize(
    ("function_ids", "device_class"),
    [
        (FUNCTION_IDS_AWNING_ACTUATOR, CoverDeviceClass.AWNING),
        (FUNCTION_IDS_ATTIC_WINDOW_ACTUATOR, CoverDeviceClass.WINDOW),
    ],
)
def test_cover_without_stop_or_position(
    function_ids: list[int], device_class: CoverDeviceClass
) -> None:
    """A cover with only up/down offers open and close, with its own device class."""
    cover = FreeAtHomeLocalCover(
        _make(FahCover, {PID_MOVE_UP_DOWN: "idp0000"}, function_id=function_ids[0])
    )
    assert cover.supported_features == CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE
    assert cover.device_class == device_class


@pytest.mark.parametrize(
    ("pid", "raw", "expected"),
    [
        (PID_WIND_SPEED, None, None),
        (PID_WIND_SPEED, "calm", "calm"),
        (PID_WIND_SPEED, "2", 7.2),
        (PID_OUTDOOR_TEMPERATURE, "n/a", "n/a"),
        (PID_OUTDOOR_TEMPERATURE, "4.5", 4.5),
    ],
)
def test_sensor_value_conversion(pid: int, raw: str | None, expected: Any) -> None:
    """Numeric sensors convert their value; values that are no number pass through."""
    device = _make(FahSensor, {pid: "odp0000"})
    device.state = raw
    assert FreeAtHomeLocalSensor(device).native_value == expected


def test_sensor_entities_for_other_devices() -> None:
    """Unknown sensor types get a plain sensor; other models add no sensors."""
    unknown = _make(FahSensor, {PID_MEASURED_BRIGHTNESS + 0x1000: "odp0000"})
    assert unknown.type is None
    plain_thermostat = _make(FahThermostat, {PID_CONTROLLER_ON_OFF: "odp0000"})
    light = _make(FahLight, {PID_SWITCH_ON_OFF: "idp0000"})
    entities = _build_sensor_entities([unknown, plain_thermostat, light])
    assert [type(entity).__name__ for entity in entities] == [
        "FreeAtHomeLocalSensor",
        "FreeAtHomeLocalThermostatTemperatureSensor",
    ]
    assert not hasattr(entities[0], "entity_description")


def test_lock_state_unknown_until_reported() -> None:
    """A door opener without a reported state is neither locked nor unlocked."""
    lock = FreeAtHomeLocalLock(_make(FahLock, {}, function_id=FUNCTION_IDS_DOOR_OPENER[0]))
    assert lock.is_locked is None


def test_entity_outside_a_platform_has_no_device_and_reads_extras() -> None:
    """Before it is added, an entity has no device; extra values come from the model."""
    lock = FreeAtHomeLocalLock(_make(FahLock, {}, function_id=FUNCTION_IDS_DOOR_OPENER[0]))
    assert lock.device_info is None
    assert lock.get_extra_attr("serialnumber") == "ABB700D10099"
    assert lock.get_extra_attr("missing", "fallback") == "fallback"


async def test_event_entity_ignores_presses_it_does_not_offer() -> None:
    """A button without long-press support ignores holds and undecodable events."""
    device = _make(FahBinarySensor, {PID_SWITCH_ON_OFF: "odp0000"}, function_id=0x0001)
    assert 0x0001 in FUNCTION_IDS_CONTROL_ELEMENT
    event = FreeAtHomeLocalControlEvent(device)
    assert event.event_types == list(PRESS_EVENT_TYPES)
    assert not set(HOLD_EVENT_TYPES) & set(event.event_types)
    with (
        patch.object(event, "_trigger_event") as trigger,
        patch.object(event, "async_write_ha_state"),
    ):
        await event.async_added_to_hass()
        callback = device._datapoint_updated_cbs[-1]
        await callback(device, {"command": "dim_start", "direction": "up"})
        await callback(device, {"command": "unknown"})
    trigger.assert_not_called()


async def test_doorbell_pulse_restarts_and_is_cancelled_on_removal(hass: HomeAssistant) -> None:
    """A second ring restarts the reset pulse; removing the entity cancels it."""
    device = _make(FahBinarySensor, {PID_SWITCH_ON_OFF: "odp0000"}, function_id=0x001F)
    assert 0x001F in FUNCTION_IDS_DOOR_CALL_SENSOR
    doorbell = FreeAtHomeLocalBinarySensor(device, hass)
    with patch.object(doorbell, "async_write_ha_state"):
        await doorbell.async_added_to_hass()
        device.state = "1"
        await device.after_update()
        first = doorbell._reset_task
        assert first is not None
        device.state = "1"
        await device.after_update()
        second = doorbell._reset_task
        assert second is not first
        await asyncio.sleep(0)
        assert first.cancelled() or first.done()
        await doorbell.async_will_remove_from_hass()
        await asyncio.sleep(0)
        assert second.done()
    assert device.state == "1"


async def test_binary_sensor_without_hass_skips_pulse_and_bus_event() -> None:
    """Without Home Assistant, a ring starts no reset task and fires no bus event."""
    device = _make(FahBinarySensor, {PID_SWITCH_ON_OFF: "odp0000"}, function_id=0x001F)
    doorbell = FreeAtHomeLocalBinarySensor(device)
    with patch.object(doorbell, "async_write_ha_state"):
        await doorbell.async_added_to_hass()
        device.state = "1"
        await device.after_update()
        assert doorbell._reset_task is None
        await device._datapoint_updated_cbs[-1](device, {"command": "pressed"})


async def test_switch_turn_on(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    mock_sysap: MockSysApServer,
    entity_registry: er.EntityRegistry,
) -> None:
    """Turning a switch on writes the datapoint and reports on right away."""
    entity_id = entity_registry.async_get_entity_id(
        Platform.SWITCH, DOMAIN, f"{SYSAP_UUID}/ABB700D10001/ch0003"
    )
    assert entity_id is not None
    await hass.services.async_call("switch", "turn_off", {"entity_id": entity_id}, blocking=True)
    await hass.services.async_call("switch", "turn_on", {"entity_id": entity_id}, blocking=True)
    assert hass.states.get(entity_id).state == "on"
    assert any(
        rec[0] == "PUT_DP" and rec[1].startswith("ABB700D10001.ch0003.") and rec[-1] == "1"
        for rec in mock_sysap.recorded
    )
