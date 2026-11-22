"""Tests for FreeAtHomeController and all Local API device models."""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock

import pytest

from custom_components.freeathome_local.api.client import FreeAtHomeLocalApiClient
from custom_components.freeathome_local.api.controller import FreeAtHomeController
from custom_components.freeathome_local.api.devices import (
    FahBinarySensor,
    FahCover,
    FahFan,
    FahLight,
    FahLightGroup,
    FahLock,
    FahScene,
    FahSensor,
    FahSwitch,
    FahThermostat,
    FahTrigger,
)
from custom_components.freeathome_local.api.devices.binary_sensor import CYCLIC_PERIOD
from custom_components.freeathome_local.binary_sensor import FreeAtHomeLocalBinarySensor
from custom_components.freeathome_local.climate import FreeAtHomeLocalThermostat
from custom_components.freeathome_local.sensor import (
    FreeAtHomeLocalDimmingStatusSensor,
    FreeAtHomeLocalSensor,
    FreeAtHomeLocalThermostatTemperatureSensor,
)

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "configuration.json")
SYSAP_UUID = "00000000-0000-0000-0000-000000000000"


def _load_fixture() -> dict:
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _make_controller(
    *,
    switch_as_x: bool = True,
    name_prefix: str = "",
    include_orphan_channels: bool = False,
) -> FreeAtHomeController:
    client = FreeAtHomeLocalApiClient("192.168.1.50", "apiuser", "secret")
    client.set_datapoint = AsyncMock(return_value={})  # type: ignore[method-assign]
    client.set_parameter = AsyncMock(return_value={})  # type: ignore[method-assign]
    controller = FreeAtHomeController(
        client,
        switch_as_x=switch_as_x,
        name_prefix=name_prefix,
        include_orphan_channels=include_orphan_channels,
    )
    controller.load_configuration(_load_fixture())
    return controller


async def test_discovery_prefix_and_filtering() -> None:
    """Verify device discovery, prefixing, Hue and orphan filtering; rooms become areas."""
    ctrl = _make_controller(switch_as_x=True, name_prefix="Local ")
    try:
        # Hue device HUE00000001 must be ignored
        assert all(dev.serialnumber != "HUE00000001" for dev in ctrl.devices)
        # Unassigned spare channel ch0004 must be ignored by default
        assert all(
            not (dev.serialnumber == "ABB700D10001" and dev.channel_id == "ch0004")
            for dev in ctrl.devices
        )
        # Virtual device 6000A1B2C3D4 and timer profile FFFF4A000001 without room ARE included
        assert any(dev.serialnumber == "6000A1B2C3D4" for dev in ctrl.devices)
        assert any(dev.serialnumber == "FFFF4A000001" for dev in ctrl.devices)

        ceiling_switch = next(
            dev
            for dev in ctrl.get_devices("switch")
            if dev.serialnumber == "ABB700D10001" and dev.channel_id == "ch0003"
        )
        assert ceiling_switch.name == "Local Ceiling Lamp"
        assert ceiling_switch.physical_device_key == f"{SYSAP_UUID}_ABB700D10001"
        assert ceiling_switch.device_info["model"] == "Sensor/switch actuator 1/1-gang"
        assert ceiling_switch.device_info["suggested_area"] == "Living Room"
        assert ceiling_switch.unique_id == f"{SYSAP_UUID}/ABB700D10001/ch0003"
    finally:
        await ctrl.close()


async def test_include_orphan_channels_option() -> None:
    """Verify orphan physical channels are included when configured."""
    ctrl = _make_controller(include_orphan_channels=True)
    try:
        assert any(
            dev.serialnumber == "ABB700D10001" and dev.channel_id == "ch0004"
            for dev in ctrl.devices
        )
    finally:
        await ctrl.close()


async def test_lights_dimmer_color_temp_rgb_and_group() -> None:
    """Verify dimming, Kelvin color temp interpolation, RGB, and light groups."""
    ctrl = _make_controller()
    try:
        lights = ctrl.get_devices("light")
        dimmer = next(
            d for d in lights if d.channel_id == "ch0000" and d.serialnumber == "ABB700D10002"
        )
        assert isinstance(dimmer, FahLight)
        assert dimmer.is_on() is True
        assert dimmer.get_brightness() == 60
        dimmer.set_brightness(35)
        await dimmer.turn_on()
        ctrl.client.set_datapoint.assert_called_with(  # type: ignore[attr-defined]
            SYSAP_UUID, "ABB700D10002", "ch0000", "idp0001", "35"
        )

        tunable = next(
            d for d in lights if d.channel_id == "ch0001" and d.serialnumber == "ABB700D10002"
        )
        assert isinstance(tunable, FahLight)
        assert tunable.min_color_temp == 2700
        assert tunable.max_color_temp == 6500
        assert tunable.get_color_temp() == 4600
        tunable.set_color_temp(2700)
        assert tunable.color_temp_percent == 0
        tunable.set_color_temp(6500)
        assert tunable.color_temp_percent == 100

        rgb = next(
            d for d in lights if d.channel_id == "ch0002" and d.serialnumber == "ABB700D10002"
        )
        assert isinstance(rgb, FahLight)
        assert rgb.get_rgb_color() == (255, 128, 0)
        rgb.set_rgb_color(10, 20, 30)
        await rgb.turn_on()
        ctrl.client.set_datapoint.assert_any_call(  # type: ignore[attr-defined]
            SYSAP_UUID, "ABB700D10002", "ch0002", "idp0002", "10,20,30"
        )

        group = next(d for d in lights if isinstance(d, FahLightGroup))
        await group.turn_on()
        ctrl.client.set_datapoint.assert_any_call(  # type: ignore[attr-defined]
            SYSAP_UUID, "FFFF40000001", "ch0000", "idp0000", "1"
        )
    finally:
        await ctrl.close()


async def test_cover_climate_fan_lock_trigger_scene() -> None:
    """Verify cover inversion, thermostat, ceiling fan, lock, trigger, and scene."""
    ctrl = _make_controller()
    try:
        cover = next(c for c in ctrl.get_devices("cover") if c.serialnumber == "ABB700D10003")
        assert isinstance(cover, FahCover)
        assert cover.device_class() == "shutter"
        assert cover.get_cover_position() == 75  # 100 - 25
        assert cover.get_cover_tilt_position() == 50
        await cover.set_cover_position(80)
        ctrl.client.set_datapoint.assert_called_with(  # type: ignore[attr-defined]
            SYSAP_UUID, "ABB700D10003", "ch0000", "idp0002", "20"
        )
        await cover.set_forced_cover_position("closed")
        ctrl.client.set_datapoint.assert_called_with(  # type: ignore[attr-defined]
            SYSAP_UUID, "ABB700D10003", "ch0000", "idp0004", "3"
        )

        shutter_group = next(
            c for c in ctrl.get_devices("cover") if c.serialnumber == "FFFF40010001"
        )
        assert isinstance(shutter_group, FahCover)
        assert shutter_group.device_info["model"] == "Shutter group"
        assert shutter_group.get_cover_position() == 50
        await shutter_group.set_cover_position(70)
        ctrl.client.set_datapoint.assert_called_with(  # type: ignore[attr-defined]
            SYSAP_UUID, "FFFF40010001", "ch0000", "odp0005", "30"
        )

        timer_36 = next(s for s in ctrl.get_devices("switch") if s.serialnumber == "FFFF4A000002")
        assert isinstance(timer_36, FahSwitch)
        assert timer_36.is_on() is True
        await timer_36.turn_off()
        ctrl.client.set_datapoint.assert_called_with(  # type: ignore[attr-defined]
            SYSAP_UUID, "FFFF4A000002", "ch0000", "idp0000", "0"
        )

        thermostat = ctrl.get_devices("climate")[0]
        assert isinstance(thermostat, FahThermostat)
        assert thermostat.state is True
        assert thermostat.ecomode is False
        assert thermostat.current_temperature == 20.8
        assert thermostat.target_temperature == 21.5
        assert thermostat.current_actuator == 42.0
        assert thermostat.temperature_correction == -0.5
        assert thermostat.fan_stage == "low"
        await thermostat.set_fan_stage("high")
        ctrl.client.set_datapoint.assert_called_with(  # type: ignore[attr-defined]
            SYSAP_UUID, "ABB700D10004", "ch0000", "idp0003", "3"
        )
        await thermostat.set_temperature_correction(1.0)
        ctrl.client.set_parameter.assert_called_with(  # type: ignore[attr-defined]
            SYSAP_UUID, "ABB700D10004", "ch0000", "par0001", "1.00"
        )

        fan = ctrl.get_devices("fan")[0]
        assert isinstance(fan, FahFan)
        assert fan.state is True
        assert fan.percentage == 75
        await fan.set_percentage(50)
        ctrl.client.set_datapoint.assert_called_with(  # type: ignore[attr-defined]
            SYSAP_UUID, "ABB700D10005", "ch0000", "idp0001", "50"
        )

        lock = ctrl.get_devices("lock")[0]
        assert isinstance(lock, FahLock)
        assert lock.state == "0"
        await lock.unlock()
        ctrl.client.set_datapoint.assert_called_with(  # type: ignore[attr-defined]
            SYSAP_UUID, "ABB700D10010", "ch0000", "idp0000", "1"
        )

        trigger = ctrl.get_devices("button")[0]
        assert isinstance(trigger, FahTrigger)
        await trigger.press()
        ctrl.client.set_datapoint.assert_called_with(  # type: ignore[attr-defined]
            SYSAP_UUID, "ABB700D10010", "ch0002", "idp0000", "1"
        )

        scene = ctrl.get_devices("scene")[0]
        assert isinstance(scene, FahScene)
        await scene.activate()
        ctrl.client.set_datapoint.assert_called_with(  # type: ignore[attr-defined]
            SYSAP_UUID, "FFFF48000001", "ch0000", "odp0000", "1"
        )
    finally:
        await ctrl.close()


async def test_sensors_including_energy_air_quality_and_weather() -> None:
    """Verify numeric sensors across weather, air quality, and energy management."""
    ctrl = _make_controller()
    try:
        sensors = ctrl.get_devices("sensor")
        by_type = {dev.type: dev for dev in sensors if isinstance(dev, FahSensor)}
        assert by_type["pv_power"].state == "4250"
        assert by_type["grid_power"].state == "-1800"
        assert by_type["battery_power"].state == "1200"
        assert by_type["battery_soc"].state == "88"
        assert by_type["humidity"].state == "48"
        assert by_type["co2"].state == "612"
        assert by_type["voc"].state == "120"
        assert by_type["temperature"].state == "14.2"
        assert by_type["windstrength"].state == "5.0"
        assert by_type["windforce"].state == "3"
        # Ensure multi-sensor channels produce unique lookup keys
        lookup_keys = [dev.lookup_key for dev in sensors]
        assert len(lookup_keys) == len(set(lookup_keys))
    finally:
        await ctrl.close()


async def test_binary_sensor_dimming_events_cyclic_filter_and_ws_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify WebSocket datapoint/param updates, DPT 3.007 dimming, 840s filter, scenes, and dynamic devices."""
    ctrl = _make_controller()
    events: list[dict] = []
    scene_triggers: list[tuple[str, dict]] = []
    vdev_cmds: list[tuple[str, str, str, str, str]] = []
    added_batches: list[list] = []

    rocker = next(
        d
        for d in ctrl.get_devices("binary_sensor")
        if isinstance(d, FahBinarySensor)
        and d.serialnumber == "ABB700D10001"
        and d.channel_id == "ch0000"
    )
    assert rocker.supports_dimming_status() is True
    rocker.register_datapoint_updated_cb(lambda _dev, ev: _append_async(events, ev))
    ctrl.register_scene_triggered_cb(lambda sysap, sc: _append_async(scene_triggers, (sysap, sc)))
    ctrl.register_virtual_device_command_cb(
        lambda s, ser, ch, dp, val: _append_async(vdev_cmds, (s, ser, ch, dp, val))
    )
    ctrl.register_devices_added_cb(lambda devs: _append_async(added_batches, devs))

    now = [1000.0]
    monkeypatch.setattr(
        "custom_components.freeathome_local.api.devices.binary_sensor.time.monotonic",
        lambda: now[0],
    )

    try:
        # 1. Dim start up (raw "9") and dim stop up (raw "8")
        await ctrl.handle_ws_message(
            {
                SYSAP_UUID: {
                    "datapoints": {"ABB700D10001/ch0000/odp0001": "9"},
                }
            }
        )
        now[0] += 1.0
        await ctrl.handle_ws_message(
            {
                SYSAP_UUID: {
                    "datapoints": {"ABB700D10001/ch0000/odp0001": "8"},
                }
            }
        )
        assert [e["command"] for e in events] == ["dim_start", "dim_stop"]
        assert [e["direction"] for e in events] == ["up", "up"]

        # 2. Press and 840s cyclic repeat suppression
        events.clear()
        await ctrl.handle_ws_message(
            {SYSAP_UUID: {"datapoints": {"ABB700D10001/ch0000/odp0000": "1"}}}
        )
        now[0] += CYCLIC_PERIOD
        await ctrl.handle_ws_message(
            {SYSAP_UUID: {"datapoints": {"ABB700D10001/ch0000/odp0000": "1"}}}
        )
        assert len(events) == 1  # cyclic duplicate suppressed

        # 3. Virtual device command + scene triggered + runtime devicesAdded + devicesRemoved
        removed_fan = ctrl.get_devices("fan")[0]
        removed_serials: list[tuple[str, str]] = []

        async def _on_removed(sysap_uuid: str, serial: str) -> None:
            removed_serials.append((sysap_uuid, serial))

        ctrl.register_devices_removed_cb(_on_removed)
        await ctrl.handle_ws_message(
            {
                SYSAP_UUID: {
                    "datapoints": {"6000A1B2C3D4/ch0000/idp0000": "1"},
                    "scenesTriggered": {"6000A1B2C3D4": {"channels": {}}},
                    "devices": {
                        "ABB700NEW001": {
                            "displayName": "Dynamic Switch",
                            "interface": "TP",
                            "floor": "01",
                            "room": "01",
                            "channels": {
                                "ch0000": {
                                    "displayName": "Dynamic Switch",
                                    "functionID": "0007",
                                    "inputs": {"idp0000": {"pairingID": 1, "value": "0"}},
                                    "outputs": {"odp0000": {"pairingID": 256, "value": "1"}},
                                }
                            },
                        }
                    },
                    "devicesRemoved": ["ABB700D10005"],
                }
            }
        )
        assert vdev_cmds == [(SYSAP_UUID, "6000A1B2C3D4", "ch0000", "idp0000", "1")]
        ctrl.client.set_datapoint.assert_any_call(  # type: ignore[attr-defined]
            SYSAP_UUID, "6000A1B2C3D4", "ch0000", "odp0000", "1"
        )
        assert len(scene_triggers) == 1
        assert len(added_batches) == 1
        assert added_batches[0][0].serialnumber == "ABB700NEW001"
        # The removed fan is forgotten (and was marked unavailable on its way out).
        assert ctrl.get_devices("fan") == []
        assert removed_fan.available is False
        assert removed_serials == [(SYSAP_UUID, "ABB700D10005")]
        assert f"{SYSAP_UUID}_ABB700D10005" not in ctrl.configured_device_keys()
        assert not any(dev is removed_fan for dev in ctrl.monitored_datapoints.values())
    finally:
        await ctrl.close()


async def test_binary_sensor_device_classes() -> None:
    """Verify BinarySensorDeviceClass mapping across window, motion, rain, frost, wind, smoke, co."""
    ctrl = _make_controller()
    try:
        # Doorbell & Window contact from fixture
        doorbell = next(
            d
            for d in ctrl.get_devices("binary_sensor")
            if isinstance(d, FahBinarySensor) and d.is_door_call_sensor()
        )
        window = next(
            d
            for d in ctrl.get_devices("binary_sensor")
            if isinstance(d, FahBinarySensor) and d.is_window_door_sensor()
        )
        assert FreeAtHomeLocalBinarySensor(doorbell, object()).device_class == "occupancy"  # type: ignore[arg-type]
        assert FreeAtHomeLocalBinarySensor(window, object()).device_class == "window"  # type: ignore[arg-type]

        # Direct model coverage for motion, rain, frost, wind, smoke, co
        for fid, dps, expected_cls in (
            (0x0011, {0x0006: "odp0000"}, "motion"),
            (0x000E, {0x0027: "odp0000"}, "moisture"),
            (0x000D, {0x0026: "odp0000"}, "cold"),
            (0x000C, {0x0025: "odp0000"}, "safety"),
            (0x007D, {0x02C3: "odp0000"}, "smoke"),
            (0x007E, {0x02C4: "odp0000"}, "carbon_monoxide"),
        ):
            dev = FahBinarySensor(ctrl, {}, "SER", "ch0000", fid, "Test", datapoints=dps)
            assert FreeAtHomeLocalBinarySensor(dev, object()).device_class == expected_cls  # type: ignore[arg-type]
    finally:
        await ctrl.close()


async def test_sysap_36_parameters_empty_values_names_and_dimming_status() -> None:
    """Verify SysAP 3.6.0 string parameters, empty value skipping, name cleanup, and dimming status translation."""
    client = FreeAtHomeLocalApiClient("192.168.1.50", "apiuser", "secret")
    ctrl = FreeAtHomeController(client)
    try:
        ctrl.load_configuration(
            {
                SYSAP_UUID: {
                    "sysapName": "SysAP 3.6",
                    "floorplan": {
                        "floors": {"01": {"name": "Top Floor", "rooms": {"01": {"name": "Office"}}}}
                    },
                    "devices": {
                        "ABB700TEST36": {
                            "displayName": "Office Light Switch",
                            "deviceId": "1017",
                            "floor": "01",
                            "room": "01",
                            "channels": {
                                "ch0000": {
                                    "displayName": "Office Light Switch Office Light Switch Button",
                                    "functionID": "1",
                                    "outputs": {
                                        "odp0000": {"pairingID": 1, "value": "0"},
                                        "odp0001": {"pairingID": 16, "value": ""},
                                    },
                                },
                                "ch0001": {
                                    "displayName": "Office Light Switch Rocker",
                                    "functionID": "1",
                                    "outputs": {
                                        "odp0000": {"pairingID": 1, "value": ""},
                                        "odp0001": {"pairingID": 16, "value": ""},
                                    },
                                },
                            },
                        },
                        "ABB700RT36": {
                            "displayName": "Office RT ",
                            "deviceId": "1004",
                            "floor": "01",
                            "room": "01",
                            "channels": {
                                "ch0000": {
                                    "displayName": "Office RT ",
                                    "functionID": "23",
                                    "outputs": {
                                        "odp0006": {"pairingID": 51, "value": "21"},
                                        "odp0008": {"pairingID": 56, "value": "1"},
                                        "odp0010": {"pairingID": 304, "value": "21.2"},
                                    },
                                    "parameters": {
                                        "par001b": "-1.5",
                                    },
                                }
                            },
                        },
                        "ABB700000000": {
                            "interface": "sysap",
                            "deviceId": "FFFF",
                            "displayName": "SysAP",
                            "channels": {
                                "ch0000": {
                                    "displayName": "Day/night switchover",
                                    "functionID": "25",
                                    "inputs": {"idp0000": {"pairingID": 20, "value": ""}},
                                    "outputs": {"odp0000": {"pairingID": 18, "value": "0"}},
                                }
                            },
                        },
                        "ABB674605479": {
                            "interface": "TP",
                            "deviceId": "1038",
                            "displayName": "Touch-Panel",
                            "floor": "01",
                            "room": "01",
                            "channels": {
                                "ch0015": {
                                    "displayName": "Corridor light",
                                    "functionID": "21",
                                    "inputs": {"idp0000": {"pairingID": 2, "value": ""}},
                                    "outputs": {"odp0000": {"pairingID": 256, "value": "0"}},
                                },
                                "ch0016": {
                                    "displayName": "Door Entry System Call Level Actuator",
                                    "functionID": "1d",
                                    "inputs": {"idp0000": {"pairingID": 2, "value": ""}},
                                    "outputs": {"odp0000": {"pairingID": 256, "value": "0"}},
                                },
                            },
                        },
                    },
                }
            }
        )

        bs_list = ctrl.get_devices("binary_sensor")
        ch0 = next(b for b in bs_list if b.channel_id == "ch0000")
        ch1 = next(b for b in bs_list if b.channel_id == "ch0001")
        assert ch0.name == "Office Light Switch Button"
        assert ch0.state == "0"
        assert ch1.name == "Office Light Switch"
        # Empty string value did not falsely turn ch1 state to "1"
        assert ch1.state is None

        # Dimming status sensor relies on translation_key rather than _attr_name
        dim_sensor = FreeAtHomeLocalDimmingStatusSensor(ch0)  # type: ignore[arg-type]
        assert "_attr_name" not in dim_sensor.__dict__
        assert dim_sensor.translation_key == "dimming_status"

        rt = ctrl.get_devices("climate")[0]
        assert isinstance(rt, FahThermostat)
        assert rt.name == "Office RT"
        assert rt.device_info["name"] == "Office RT"
        assert rt.device_info["serial_number"] == "ABB700RT36"
        assert rt.device_info["model"] == "Room temperature controller"
        assert rt.temperature_correction == -1.5

        ha_thermostat = FreeAtHomeLocalThermostat(rt)
        assert ha_thermostat.temperature_unit == "°C"
        assert ha_thermostat.current_temperature == 21.2
        assert ha_thermostat.target_temperature == 21.0

        rt_temp_sensor = FreeAtHomeLocalThermostatTemperatureSensor(rt)
        assert "_attr_name" not in rt_temp_sensor.__dict__
        assert rt_temp_sensor.translation_key == "thermostat_temperature"

        valve_dev = FahSensor(
            ctrl,
            {},
            "ABBVALVE1",
            "ch0000",
            0x0027,
            "Office Valve",
            datapoints={0x0131: "odp0001"},
        )
        ha_valve_sensor = FreeAtHomeLocalSensor(valve_dev)
        assert "_attr_name" not in ha_valve_sensor.__dict__
        assert ha_valve_sensor.translation_key == "valve_volume_flow"

        client.set_datapoint = AsyncMock()  # type: ignore[method-assign]
        switches = {(s.serialnumber, s.channel_id): s for s in ctrl.get_devices("switch")}
        day_night = switches[("ABB700000000", "ch0000")]
        corridor_light = switches[("ABB674605479", "ch0015")]
        call_level = switches[("ABB674605479", "ch0016")]
        assert isinstance(day_night, FahSwitch)
        assert day_night.device_info["model"] == "System Access Point"
        assert day_night.is_on() is False
        await day_night.turn_on()
        client.set_datapoint.assert_called_with(
            SYSAP_UUID, "ABB700000000", "ch0000", "idp0000", "1"
        )
        assert corridor_light.device_info["model"] == 'free@homeTouch 7"'
        await corridor_light.turn_on()
        client.set_datapoint.assert_called_with(
            SYSAP_UUID, "ABB674605479", "ch0015", "idp0000", "1"
        )
        assert call_level.is_on() is False
        await call_level.turn_off()
        client.set_datapoint.assert_called_with(
            SYSAP_UUID, "ABB674605479", "ch0016", "idp0000", "0"
        )
    finally:
        await ctrl.close()


async def _append_async(target: list, item) -> None:
    target.append(item)
