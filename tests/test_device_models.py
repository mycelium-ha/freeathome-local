"""Edge cases of the HA-free device models, tested without a SysAP."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.freeathome_local.api.const import (
    FUNCTION_IDS_ATTIC_WINDOW_ACTUATOR,
    FUNCTION_IDS_AWNING_ACTUATOR,
    FUNCTION_IDS_BLIND_ACTUATOR,
    FUNCTION_IDS_SWITCHING_ACTUATOR,
    PAR_MAXIMUM_COLOR_TEMPERATURE,
    PAR_MINIMUM_COLOR_TEMPERATURE,
    PID_ABSOLUTE_SET_VALUE,
    PID_COLOR_TEMPERATURE,
    PID_FAN_SPEED,
    PID_INFO_ACTUAL_DIMMING_VALUE,
    PID_INFO_COLOR_TEMPERATURE,
    PID_INFO_FAN_SPEED,
    PID_INFO_ON_OFF,
    PID_INFO_RGB,
    PID_OUTDOOR_TEMPERATURE,
    PID_RGB,
    PID_SWITCH_ON_OFF,
    PID_SYSAP_INFO_ACTUAL_DIMMING_VALUE,
    PID_SYSAP_INFO_ON_OFF,
    PID_WIND_FORCE,
)
from custom_components.freeathome_local.api.devices import (
    FahCover,
    FahFan,
    FahLight,
    FahLightGroup,
    FahSensor,
)
from custom_components.freeathome_local.api.devices.base import FahBaseDevice


def _controller() -> Any:
    controller = MagicMock()
    controller.set_datapoint = AsyncMock()
    controller.set_parameter = AsyncMock()
    return controller


def _make[T: FahBaseDevice](
    cls: type[T],
    datapoints: dict[int, str],
    *,
    function_id: int | None = None,
    parameters: dict[int, str] | None = None,
) -> T:
    return cls(
        _controller(),
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
    ("value", "expected"),
    [
        (None, None),
        (0x102030, 0x102030),
        ("  ", None),
        ("0x0000FF", 0xFF),
        ("0xZZ", None),
        ("#00ff00", 0x00FF00),
        ("#zz", None),
        ("1,2,3", 0x010203),
        ("1; 2; 3", 0x010203),
        ("1 2", None),
        ("1,a,3", None),
        ("66051", 66051),
        ("abcdef", 0xABCDEF),
        ("nope", None),
    ],
)
def test_light_parses_rgb_representations(value: Any, expected: int | None) -> None:
    """RGB values arrive as decimal, hex or separated triples."""
    light = _make(FahLight, {PID_RGB: "idp0002", PID_INFO_RGB: "odp0002"})
    assert light._parse_rgb_to_int(value) == expected


def test_light_ignores_invalid_values_and_parameters() -> None:
    """Invalid datapoint and parameter values keep the previous state."""
    light = _make(
        FahLight,
        {
            PID_INFO_ACTUAL_DIMMING_VALUE: "odp0001",
            PID_INFO_COLOR_TEMPERATURE: "odp0002",
            PID_INFO_RGB: "odp0003",
        },
        parameters={PAR_MINIMUM_COLOR_TEMPERATURE: "par0001", PAR_MAXIMUM_COLOR_TEMPERATURE: "p2"},
    )
    light.update_datapoint("odp0001", "dim")
    light.update_datapoint("odp0002", "warm")
    light.update_datapoint("odp0003", "nope")
    assert (light.brightness, light.color_temp_percent, light.rgb_color) == (None, None, None)
    assert light.get_color_temp() is None
    assert light.get_rgb_color() is None

    light.update_parameter("par0001", "cold")
    light.update_parameter("par0001", "0")
    light.update_parameter("unknown", "3000")
    assert (light.min_color_temp, light.max_color_temp) == (2700, 6500)
    light.update_parameter_value("par0001", "2000")
    light.update_parameter("p2", "5000")
    assert (light.min_color_temp, light.max_color_temp) == (2000, 5000)


async def test_light_without_capabilities_ignores_staged_values() -> None:
    """Brightness, color temperature and color are only staged when supported."""
    light = _make(FahLight, {PID_SWITCH_ON_OFF: "idp0000", PID_INFO_ON_OFF: "odp0000"})
    light.set_brightness(50)
    light.set_color_temp(3000)
    light.set_rgb_color(1, 2, 3)
    assert (light.brightness, light.color_temp_percent, light.rgb_color) == (None, None, None)
    assert not light.is_dimmer()

    light.update_datapoint("odp0000", "0")
    await light.turn_off()
    assert _written(light) == []
    await light.turn_on()
    await light.turn_on()
    assert _written(light) == [("idp0000", "1")]


async def test_light_already_on_updates_brightness_and_color_temperature() -> None:
    """A light that is on only receives the new brightness and color temperature."""
    light = _make(
        FahLight,
        {
            PID_SWITCH_ON_OFF: "idp0000",
            PID_ABSOLUTE_SET_VALUE: "idp0001",
            PID_COLOR_TEMPERATURE: "idp0002",
            PID_INFO_ON_OFF: "odp0000",
        },
    )
    light.update_datapoint("odp0000", "1")
    light.min_color_temp = light.max_color_temp = 3000
    light.set_color_temp(4000)
    assert light.color_temp_percent == 50
    light.set_brightness(150)
    await light.turn_on()
    assert _written(light) == [("idp0001", "100"), ("idp0002", "50")]


def test_light_pairing_and_parameter_ids() -> None:
    """Switching actuators are lights only when `switch_as_x` is off."""
    switching = FUNCTION_IDS_SWITCHING_ACTUATOR[0]
    assert FahLight.pairing_ids(switching) is None
    assert FahLight.pairing_ids(switching, switch_as_x=False) == {
        "inputs": [PID_SWITCH_ON_OFF],
        "outputs": [PID_INFO_ON_OFF],
    }
    assert FahLight.parameter_ids(switching) is None
    assert FahLightGroup.pairing_ids(switching) is None


async def test_light_group_falls_back_to_info_datapoint() -> None:
    """Groups without a switch input write the info datapoint and read SysAP info values."""
    group = _make(
        FahLightGroup,
        {
            PID_INFO_ON_OFF: "odp0000",
            PID_SYSAP_INFO_ON_OFF: "odp0001",
            PID_SYSAP_INFO_ACTUAL_DIMMING_VALUE: "odp0002",
            PID_ABSOLUTE_SET_VALUE: "idp0001",
        },
    )
    group.update_datapoint("odp0001", "1")
    group.update_datapoint("odp0002", "40")
    group.update_datapoint("odp0002", "bad")
    assert (group.state, group.brightness) == (True, 40)
    group.update_datapoint("odp0000", "0")
    assert group.state is False

    await group.turn_on()
    await group.turn_off()
    assert _written(group) == [("odp0000", "1"), ("idp0001", "40"), ("odp0000", "0")]

    empty = _make(FahLightGroup, {})
    await empty.turn_on()
    await empty.turn_off()
    assert _written(empty) == []
    assert empty.state is False


async def test_fan_speed_datapoints_and_zero_percentage() -> None:
    """Fans prefer the fan speed datapoint; 0 % turns the fan off."""
    fan = _make(
        FahFan,
        {PID_SWITCH_ON_OFF: "idp0000", PID_FAN_SPEED: "idp0002", PID_INFO_FAN_SPEED: "odp0002"},
    )
    await fan.set_percentage(130)
    await fan.set_percentage(0)
    assert _written(fan) == [("idp0002", "100"), ("idp0000", "0")]
    assert (fan.state, fan.percentage) == (False, 0)
    fan.update_datapoint("odp0002", "fast")
    fan.update_datapoint("odp0002", "55")
    assert fan.percentage == 55

    dimmer_fan = _make(FahFan, {PID_ABSOLUTE_SET_VALUE: "idp0001"})
    await dimmer_fan.set_percentage(30)
    assert _written(dimmer_fan) == [("idp0001", "30")]

    plain = _make(FahFan, {PID_SWITCH_ON_OFF: "idp0000"})
    assert not plain.supports_percentage()
    await plain.set_percentage(30)
    await plain.turn_on()
    assert _written(plain) == [("idp0000", "1")]


@pytest.mark.parametrize(
    ("function_ids", "expected"),
    [
        (FUNCTION_IDS_ATTIC_WINDOW_ACTUATOR, "window"),
        (FUNCTION_IDS_AWNING_ACTUATOR, "awning"),
        (FUNCTION_IDS_BLIND_ACTUATOR, "blind"),
    ],
)
def test_cover_device_class(function_ids: list[int], expected: str) -> None:
    """The cover kind follows the function ID; all of them pair like blinds."""
    cover = _make(FahCover, {}, function_id=function_ids[0])
    assert cover.device_class() == expected
    assert FahCover.pairing_ids(function_ids[0]) is not None
    assert cover.is_cover_closed() is None
    assert cover.get_cover_position() is None
    assert cover.get_cover_tilt_position() is None
    assert cover.get_forced_cover_position() is None


async def test_cover_unknown_forced_position_is_ignored() -> None:
    """An unknown forced position writes nothing."""
    cover = _make(FahCover, {}, function_id=FUNCTION_IDS_BLIND_ACTUATOR[0])
    await cover.set_forced_cover_position("sideways")
    await cover.stop_cover()
    assert _written(cover) == []


def test_sensor_type_and_lookup_key() -> None:
    """Multi-sensor channels get the datapoint in their lookup key."""
    untyped = _make(FahSensor, {})
    assert untyped.type is None
    assert untyped.name == "Test"
    wind = _make(FahSensor, {PID_WIND_FORCE: "odp0001"})
    assert wind.lookup_key.endswith("/odp0001")
    temperature = _make(FahSensor, {PID_OUTDOOR_TEMPERATURE: "odp0000"})
    assert not temperature.lookup_key.endswith("/odp0000")
    temperature.update_datapoint("odp0009", "1")
    assert temperature.state is None
    temperature.update_datapoint("odp0000", "21.5")
    assert temperature.state == "21.5"


async def test_base_device_ignores_unknown_ids_and_callbacks() -> None:
    """Writes to unknown datapoints or parameters do nothing; callbacks deregister."""
    device = _make(FahBaseDevice, {})
    await device.set_datapoint(PID_SWITCH_ON_OFF, "1")
    await device.set_parameter(PAR_MINIMUM_COLOR_TEMPERATURE, "1")
    device.controller.set_datapoint.assert_not_awaited()
    device.controller.set_parameter.assert_not_awaited()

    calls: list[FahBaseDevice] = []

    async def _cb(dev: FahBaseDevice) -> None:
        calls.append(dev)

    device.register_device_updated_cb(_cb)
    device.register_device_updated_cb(_cb)
    await device.after_update()
    device.unregister_device_updated_cb(_cb)
    device.unregister_device_updated_cb(_cb)
    await device.after_update()
    assert calls == [device]
