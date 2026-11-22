"""Edge cases of the HA-free device models that the platform tests do not reach."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.freeathome_local.api.const import (
    FUNCTION_IDS_COOLING_ACTOR,
    FUNCTION_IDS_HEATING_ACTOR,
    FUNCTION_IDS_HEATING_COOLING_ACTOR,
    FUNCTION_IDS_MOVEMENT_DETECTOR,
    FUNCTION_IDS_ROOM_TEMPERATURE_CONTROLLER,
    PID_CONTROLLER_ON_OFF_REQUEST,
    PID_FIRE_ALARM_ACTIVE,
    PID_INFO_ON_OFF,
    PID_INFO_VALUE_COOLING,
    PID_INFO_VALUE_HEATING,
    PID_MEASURED_BRIGHTNESS,
    PID_OUTDOOR_TEMPERATURE,
    PID_RELATIVE_SET_VALUE,
    PID_SWITCH_ON_OFF,
)
from custom_components.freeathome_local.api.devices import (
    FahBinarySensor,
    FahSensor,
    FahSwitch,
    FahThermostat,
)
from custom_components.freeathome_local.api.devices.base import FahBaseDevice
from custom_components.freeathome_local.api.devices.sensor import sensor_type_from_pairing_ids


def _make[T: FahBaseDevice](
    cls: type[T],
    datapoints: dict[int, str],
    *,
    function_id: int | None = None,
    parameters: dict[int, str] | None = None,
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
        parameters=parameters,
        sysap_uuid="uuid",
    )


def _written(device: FahBaseDevice) -> list[tuple[str, str]]:
    return [(c.args[2], c.args[3]) for c in device.controller.set_datapoint.await_args_list]


@pytest.mark.parametrize(
    ("function_ids", "outputs"),
    [
        (FUNCTION_IDS_MOVEMENT_DETECTOR, [PID_MEASURED_BRIGHTNESS]),
        (FUNCTION_IDS_HEATING_ACTOR, [PID_INFO_VALUE_HEATING]),
        (FUNCTION_IDS_COOLING_ACTOR, [PID_INFO_VALUE_COOLING]),
        (FUNCTION_IDS_HEATING_COOLING_ACTOR, [PID_INFO_VALUE_HEATING, PID_INFO_VALUE_COOLING]),
    ],
)
def test_sensor_pairing_ids_per_function(function_ids: list[int], outputs: list[int]) -> None:
    """Brightness of motion detectors and actuator demand values are sensors."""
    assert FahSensor.pairing_ids(function_ids[0]) == {"inputs": [], "outputs": outputs}


def test_sensor_type_skips_unmatched_datapoints_and_keeps_plain_lookup_key() -> None:
    """Unmatched datapoints do not decide the type; single-value sensors keep the channel key."""
    assert sensor_type_from_pairing_ids({PID_MEASURED_BRIGHTNESS: None}) is None  # type: ignore[dict-item]
    brightness = _make(FahSensor, {PID_MEASURED_BRIGHTNESS: "odp0000"})
    assert brightness.lookup_key == "ABB700D10099/ch0000"
    temperature = _make(FahSensor, {PID_OUTDOOR_TEMPERATURE: "odp0001"})
    assert temperature.lookup_key == "ABB700D10099/ch0000"


def test_binary_sensor_never_treats_alarms_as_keep_alive() -> None:
    """Fire and CO alarm repeats always count, even at the keep-alive period."""
    sensor = _make(FahBinarySensor, {PID_FIRE_ALARM_ACTIVE: "odp0000"})
    assert sensor._is_cyclic_repeat("odp0000", "1") is False
    assert sensor._is_cyclic_repeat("odp0000", "1") is False


@pytest.mark.parametrize("value", ["abc", "16", "-1"])
def test_binary_sensor_rejects_invalid_relative_dimming(value: str) -> None:
    """Relative dimming outside KNX DPT 3.007 is ignored without changing state."""
    assert FahBinarySensor._relative_dimming_event(value) is None
    sensor = _make(FahBinarySensor, {PID_RELATIVE_SET_VALUE: "odp0001"})
    sensor.state = "1"
    sensor.update_datapoint("odp0001", value)
    assert sensor.state == "1"


async def test_binary_sensor_ignores_empty_values_and_duplicate_callbacks() -> None:
    """Empty values are dropped; callbacks register once and unknown ones unregister quietly."""
    sensor = _make(FahBinarySensor, {PID_SWITCH_ON_OFF: "odp0000"})
    sensor.state = "1"
    sensor.update_datapoint("odp0000", "")
    assert sensor.state == "1"

    async def _cb(_device: FahBinarySensor, _event: dict[str, Any]) -> None:
        """Unused callback."""

    sensor.register_datapoint_updated_cb(_cb)
    sensor.register_datapoint_updated_cb(_cb)
    assert sensor._datapoint_updated_cbs == [_cb]
    sensor.unregister_datapoint_updated_cb(_cb)
    sensor.unregister_datapoint_updated_cb(_cb)
    assert sensor._datapoint_updated_cbs == []


async def test_thermostat_without_eco_and_unknown_ids() -> None:
    """Turning on without an eco datapoint only switches on; unknown IDs change nothing."""
    assert FahThermostat.parameter_ids(FUNCTION_IDS_HEATING_ACTOR[0]) is None
    assert FahThermostat.parameter_ids(FUNCTION_IDS_ROOM_TEMPERATURE_CONTROLLER[0]) is not None
    thermostat = _make(FahThermostat, {PID_CONTROLLER_ON_OFF_REQUEST: "idp0000"})
    await thermostat.turn_on()
    assert _written(thermostat) == [("idp0000", "1")]
    before = (thermostat.current_temperature, thermostat.temperature_correction)
    thermostat.update_datapoint("odp9999", "21.0")
    thermostat.update_parameter("par9999", "1.0")
    assert (thermostat.current_temperature, thermostat.temperature_correction) == before


async def test_switch_without_known_input_writes_switch_on_off() -> None:
    """A switch without input datapoint falls back to the plain on/off pairing ID."""
    switch = _make(FahSwitch, {PID_INFO_ON_OFF: "odp0000"})
    assert switch._resolve_input_pid() == PID_SWITCH_ON_OFF
    switch.state = True
    switch.update_datapoint("odp9999", "0")
    assert switch.is_on() is True
