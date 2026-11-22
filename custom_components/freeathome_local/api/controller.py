"""High-level controller bridging free@home Local API data to device models."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from .client import (
    FreeAtHomeAuthError,
    FreeAtHomeLocalApiClient,
    resolve_username_candidates,
)
from .const import (
    DEVICE_ID_TO_MODEL,
    FUNCTION_IDS_AIR_QUALITY_SENSOR,
    FUNCTION_IDS_ENERGY,
    FUNCTION_IDS_SYSTEM_SWITCH,
    FUNCTION_IDS_TIMER_PROFILE,
    FUNCTION_IDS_WEATHER_STATION,
    NAME_IDS_TO_BINARY_SENSOR_SUFFIX,
    PID_ABSOLUTE_SET_VALUE,
    PID_CURRENT_ABSOLUTE_POSITION_BLINDS_PERCENTAGE,
    PID_INFO_ACTUAL_DIMMING_VALUE,
    PID_INFO_ON_OFF,
    PID_SET_ABSOLUTE_POSITION_BLINDS,
    PID_SWITCH_ON_OFF,
    PROXY_VIRTUAL_SERIAL_PREFIX,
    VIRTUAL_SERIAL_PREFIX,
    parse_hex_id,
    parse_pairing_id,
)
from .devices import (
    FahBaseDevice,
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

_LOGGER = logging.getLogger(__name__)

DEVICE_CLASSES: tuple[type[FahBaseDevice], ...] = (
    FahLight,
    FahLightGroup,
    FahSwitch,
    FahTrigger,
    FahCover,
    FahBinarySensor,
    FahThermostat,
    FahFan,
    FahScene,
    FahSensor,
    FahLock,
)

VIRTUAL_INPUT_TO_OUTPUT_PID: dict[int, int] = {
    PID_SWITCH_ON_OFF: PID_INFO_ON_OFF,
    PID_ABSOLUTE_SET_VALUE: PID_INFO_ACTUAL_DIMMING_VALUE,
    PID_SET_ABSOLUTE_POSITION_BLINDS: PID_CURRENT_ABSOLUTE_POSITION_BLINDS_PERCENTAGE,
}


def _extract_floorplan(
    sysap_data: dict[str, Any],
) -> dict[str, dict[str, str]]:
    """Build `{floor_id: {room_id: room_name}}` mapping from Local API config."""
    result: dict[str, dict[str, str]] = {}
    floorplan = sysap_data.get("floorplan") or {}
    floors = floorplan.get("floors") or {}
    for floor_id, floor_data in floors.items():
        if not isinstance(floor_data, dict):
            continue
        rooms_map: dict[str, str] = {}
        for room_id, room_data in (floor_data.get("rooms") or {}).items():
            if isinstance(room_data, dict):
                rooms_map[room_id] = str(room_data.get("name", "")).strip()
        result[floor_id] = rooms_map
    return result


def _match_datapoints(
    channel_data: dict[str, Any],
    wanted_pids: dict[str, list[int]],
) -> tuple[dict[int, str], dict[str, str]]:
    """Match channel `inputs` and `outputs` against wanted pairing IDs.

    Returns `(pid_to_dp_id, dp_id_to_initial_value)`.
    """
    matched: dict[int, str] = {}
    initial_values: dict[str, str] = {}

    for section in ("inputs", "outputs"):
        wanted = set(wanted_pids.get(section, []))
        if not wanted:
            continue
        section_data = channel_data.get(section) or {}
        for dp_id, dp_info in section_data.items():
            if not isinstance(dp_info, dict):
                continue
            pid = parse_pairing_id(dp_info.get("pairingID"))
            if pid in wanted:
                matched[pid] = dp_id
                if dp_info.get("value") is not None and str(dp_info["value"]) != "":
                    initial_values[dp_id] = str(dp_info["value"])

    return matched, initial_values


def _clean_channel_display_name(device_display_name: str, channel_display_name: str) -> str:
    """Strip redundant device displayName prefix from SysAP 3.x channel names."""
    device_display_name = device_display_name.strip()
    channel_display_name = channel_display_name.strip()
    if device_display_name and channel_display_name.startswith(f"{device_display_name} "):
        remainder = channel_display_name[len(device_display_name) :].strip()
        if remainder.lower() == "rocker":
            return device_display_name
        if remainder:
            return remainder
    return channel_display_name


def _match_parameters(
    channel_data: dict[str, Any],
    wanted_params: dict[str, list[int]] | None,
) -> tuple[dict[int, str], dict[str, str]]:
    """Match channel `parameters` against wanted parameter IDs."""
    matched: dict[int, str] = {}
    initial_values: dict[str, str] = {}
    if not wanted_params:
        return matched, initial_values

    wanted = set(wanted_params.get("parameters", []))
    if not wanted:
        return matched, initial_values

    params_data = channel_data.get("parameters") or {}
    for param_id, param_info in params_data.items():
        if isinstance(param_info, dict):
            parsed_id = parse_hex_id(param_info.get("parameterID"))
            val = param_info.get("value")
        else:
            lower = param_id.lower()
            raw_hex = (
                param_id[3:]
                if lower.startswith("par")
                else (param_id[2:] if lower.startswith("pm") else param_id)
            )
            parsed_id = parse_hex_id(raw_hex)
            val = param_info
        if parsed_id in wanted:
            matched[parsed_id] = param_id
            if val is not None and str(val) != "":
                initial_values[param_id] = str(val)

    return matched, initial_values


class FreeAtHomeController:
    """Coordinates REST discovery, device models, and WebSocket state updates."""

    def __init__(
        self,
        client: FreeAtHomeLocalApiClient,
        *,
        switch_as_x: bool = True,
        name_prefix: str = "",
        include_orphan_channels: bool = False,
    ) -> None:
        """Initialize the free@home Local API controller."""
        self.client = client
        self.switch_as_x = switch_as_x
        self.name_prefix = name_prefix
        self.include_orphan_channels = include_orphan_channels

        self.devices: list[FahBaseDevice] = []
        self._device_keys: set[tuple[str, str]] = set()
        self.monitored_datapoints: dict[tuple[str, str], FahBaseDevice] = {}
        self.monitored_parameters: dict[tuple[str, str], FahBaseDevice] = {}
        self.virtual_serials: set[tuple[str, str]] = set()

        self.raw_configuration: dict[str, Any] = {}
        self.sysap_uuids: list[str] = []
        self.primary_sysap_uuid: str = "00000000-0000-0000-0000-000000000000"
        self.sysap_names: dict[str, str] = {}
        self.sysap_serial: str | None = None
        self.sysap_version: str | None = None
        self.ws_connected: bool = True
        self._settings_data: dict[str, Any] | None = None

        self._ws_frame_listeners: list[Callable[[dict[str, Any]], None]] = []
        self._scene_triggered_cbs: list[Callable[[str, dict[str, Any]], Awaitable[None]]] = []
        self._virtual_cmd_cbs: list[Callable[[str, str, str, str, str], Awaitable[None]]] = []
        self._devices_added_cbs: list[Callable[[list[FahBaseDevice]], Awaitable[None]]] = []
        self._devices_removed_cbs: list[Callable[[str, str], Awaitable[None]]] = []
        self._auth_failed_cb: Callable[[], None] | None = None
        self._pending_tasks: set[asyncio.Task[None]] = set()
        self._settings_loaded: bool = False

    def set_auth_failed_callback(self, cb: Callable[[], None] | None) -> None:
        """Register callback invoked when WebSocket auth fails."""
        self._auth_failed_cb = cb

    def add_ws_frame_listener(self, listener: Callable[[dict[str, Any]], None]) -> None:
        """Subscribe to raw WebSocket JSON frames (used by monitor service)."""
        if listener not in self._ws_frame_listeners:
            self._ws_frame_listeners.append(listener)

    def remove_ws_frame_listener(self, listener: Callable[[dict[str, Any]], None]) -> None:
        """Unsubscribe from raw WebSocket JSON frames."""
        if listener in self._ws_frame_listeners:
            self._ws_frame_listeners.remove(listener)

    def register_scene_triggered_cb(
        self, cb: Callable[[str, dict[str, Any]], Awaitable[None]]
    ) -> None:
        """Register callback for `scenesTriggered` WebSocket frames."""
        if cb not in self._scene_triggered_cbs:
            self._scene_triggered_cbs.append(cb)

    def register_virtual_device_command_cb(
        self, cb: Callable[[str, str, str, str, str], Awaitable[None]]
    ) -> None:
        """Register callback for incoming commands to virtual devices."""
        if cb not in self._virtual_cmd_cbs:
            self._virtual_cmd_cbs.append(cb)

    def register_devices_removed_cb(self, cb: Callable[[str, str], Awaitable[None]]) -> None:
        """Register an async callback `(sysap_uuid, serialnumber)` for removed devices."""
        if cb not in self._devices_removed_cbs:
            self._devices_removed_cbs.append(cb)

    def configured_device_keys(self) -> set[str]:
        """Return the keys of all devices and channels in the SysAP configuration.

        Physical devices as `{sysap_uuid}_{serial}`, channels as
        `{sysap_uuid}_{serial}_{channel_id}`, whether or not they produce entities.
        """
        keys: set[str] = set()
        for sysap_uuid, sysap_data in self.raw_configuration.items():
            if not isinstance(sysap_data, dict):
                continue
            for serial, device_data in (sysap_data.get("devices") or {}).items():
                keys.add(f"{sysap_uuid}_{serial}")
                if isinstance(device_data, dict):
                    for channel_id in device_data.get("channels") or {}:
                        keys.add(f"{sysap_uuid}_{serial}_{channel_id}")
        return keys

    def _forget_device(self, sysap_uuid: str, serialnumber: str) -> list[FahBaseDevice]:
        """Drop all models of a device the SysAP removed; return them."""
        removed = [
            dev
            for dev in self.devices
            if dev.sysap_uuid == sysap_uuid and dev.serialnumber == serialnumber
        ]
        if not removed:
            return []
        self.devices = [dev for dev in self.devices if dev not in removed]
        for dev in removed:
            self._device_keys.discard((sysap_uuid, dev.lookup_key))
        for mapping in (self.monitored_datapoints, self.monitored_parameters):
            for key in [k for k, dev in mapping.items() if dev in removed]:
                del mapping[key]
        self.virtual_serials.discard((sysap_uuid, serialnumber))
        sysap_data = self.raw_configuration.get(sysap_uuid)
        if isinstance(sysap_data, dict) and isinstance(sysap_data.get("devices"), dict):
            sysap_data["devices"].pop(serialnumber, None)
        return removed

    def _update_reachability(
        self, sysap_uuid: str, serialnumber: str, unresponsive: bool
    ) -> list[FahBaseDevice]:
        """Apply the SysAP's `unresponsive` flag to a device's models; return changed ones."""
        sysap_data = self.raw_configuration.get(sysap_uuid)
        if isinstance(sysap_data, dict):
            cached = (sysap_data.get("devices") or {}).get(serialnumber)
            if isinstance(cached, dict):
                cached["unresponsive"] = unresponsive
        changed = [
            dev
            for dev in self.devices
            if dev.sysap_uuid == sysap_uuid
            and dev.serialnumber == serialnumber
            and dev.available == unresponsive
        ]
        for dev in changed:
            dev.available = not unresponsive
        if changed:
            if unresponsive:
                _LOGGER.warning("free@home device %s is unresponsive", serialnumber)
            else:
                _LOGGER.info("free@home device %s is responding again", serialnumber)
        return changed

    def register_devices_added_cb(
        self, cb: Callable[[list[FahBaseDevice]], Awaitable[None]]
    ) -> None:
        """Register callback invoked when runtime devices are added."""
        if cb not in self._devices_added_cbs:
            self._devices_added_cbs.append(cb)

    async def _fetch_configuration_with_auth_fallback(self) -> dict[str, Any]:
        """Fetch configuration, falling back to JID localpart if display name was given."""
        if not self._settings_loaded:
            settings = await self.client.fetch_settings_json()
            self._settings_data = settings
            if settings:
                flags = settings.get("flags") or {}
                self.sysap_serial = flags.get("serialNumber")
                self.sysap_version = flags.get("version")
            self._settings_loaded = True

        try:
            return await self.client.get_configuration()
        except FreeAtHomeAuthError:
            original_user = self.client.username
            password = self.client.password
            candidates = resolve_username_candidates(self._settings_data, original_user)
            for candidate in candidates:
                if candidate == original_user:
                    continue
                _LOGGER.debug(
                    "Retrying Local API auth with resolved username %s from /settings.json",
                    candidate,
                )
                self.client.set_credentials(candidate, password)
                try:
                    return await self.client.get_configuration()
                except FreeAtHomeAuthError:
                    continue
            self.client.set_credentials(original_user, password)
            raise

    async def initialize(self) -> dict[str, Any]:
        """Fetch metadata and full configuration, then build all device models."""
        config = await self._fetch_configuration_with_auth_fallback()
        self.load_configuration(config)
        return config

    def load_configuration(self, config: dict[str, Any]) -> list[FahBaseDevice]:
        """Parse the Local API configuration dictionary into device models."""
        self.raw_configuration = config
        self.devices.clear()
        self._device_keys.clear()
        self.monitored_datapoints.clear()
        self.monitored_parameters.clear()
        self.virtual_serials.clear()
        self.sysap_uuids.clear()
        self.sysap_names.clear()

        created: list[FahBaseDevice] = []
        for sysap_uuid, sysap_data in config.items():
            if not isinstance(sysap_data, dict):
                continue
            self.sysap_uuids.append(sysap_uuid)
            self.sysap_names[sysap_uuid] = str(sysap_data.get("sysapName", "SysAP")).strip()
            floorplan = _extract_floorplan(sysap_data)
            devices_dict = sysap_data.get("devices") or {}
            created.extend(
                self._register_devices_from_dict(
                    sysap_uuid,
                    devices_dict,
                    floorplan=floorplan,
                    initializing=True,
                )
            )

        if self.sysap_uuids:
            self.primary_sysap_uuid = self.sysap_uuids[0]

        return created

    def _register_devices_from_dict(
        self,
        sysap_uuid: str,
        devices_dict: dict[str, Any],
        *,
        floorplan: dict[str, dict[str, str]] | None = None,
        initializing: bool = False,
    ) -> list[FahBaseDevice]:
        """Instantiate device models from a `{serial: device_data}` mapping."""
        if floorplan is None:
            sysap_data = self.raw_configuration.get(sysap_uuid) or {}
            floorplan = _extract_floorplan(sysap_data)

        created: list[FahBaseDevice] = []
        for serialnumber, device_data in devices_dict.items():
            if not isinstance(device_data, dict):
                continue

            interface = str(device_data.get("interface", ""))
            if interface == "hue":
                _LOGGER.debug("Skipping external Hue device %s", serialnumber)
                continue

            channels = device_data.get("channels") or {}
            if not channels:
                continue

            is_virtual = (
                interface.startswith("vdev:")
                or serialnumber.startswith(VIRTUAL_SERIAL_PREFIX)
                or serialnumber.startswith(PROXY_VIRTUAL_SERIAL_PREFIX)
            )
            if is_virtual:
                self.virtual_serials.add((sysap_uuid, serialnumber))

            device_display_name = str(device_data.get("displayName") or "").strip()
            device_floor = str(device_data.get("floor") or "")
            device_room = str(device_data.get("room") or "")
            raw_device_id = str(device_data.get("deviceId") or "")
            model_name = (
                DEVICE_ID_TO_MODEL.get(raw_device_id.upper()) or raw_device_id or "free@home Device"
            )
            device_label = device_display_name or raw_device_id or serialnumber

            device_info: dict[str, Any] = {
                "name": f"{self.name_prefix}{device_label}",
                "serial_number": serialnumber,
                "manufacturer": "ABB / Busch-Jaeger",
                "model": model_name,
                "configuration_url": self.client.base_http_url,
            }
            suggested_area = floorplan.get(device_floor, {}).get(device_room)
            if not suggested_area:
                channel_rooms = {
                    floorplan.get(str(ch.get("floor") or device_floor or ""), {}).get(
                        str(ch.get("room") or device_room or "")
                    )
                    for ch in channels.values()
                    if isinstance(ch, dict)
                }
                channel_rooms.discard(None)
                channel_rooms.discard("")
                if len(channel_rooms) == 1:
                    suggested_area = next(iter(channel_rooms))
            if suggested_area:
                device_info["suggested_area"] = suggested_area

            sw_version = device_data.get("softwareVersion") or self.sysap_version
            if sw_version:
                device_info["sw_version"] = str(sw_version)

            for channel_id, channel_data in channels.items():
                if not isinstance(channel_data, dict):
                    continue
                function_id = parse_hex_id(channel_data.get("functionID"))
                if function_id is None:
                    continue

                if channel_data.get("sameLocation") is True:
                    floor_id = device_floor
                    room_id = device_room
                else:
                    floor_id = str(channel_data.get("floor", device_floor))
                    room_id = str(channel_data.get("room", device_room))

                if (
                    not room_id
                    and not self.include_orphan_channels
                    and not is_virtual
                    and function_id
                    not in (
                        FUNCTION_IDS_TIMER_PROFILE
                        + FUNCTION_IDS_ENERGY
                        + FUNCTION_IDS_SYSTEM_SWITCH
                    )
                ):
                    _LOGGER.debug(
                        "Ignoring unassigned channel %s/%s (function 0x%04X)",
                        serialnumber,
                        channel_id,
                        function_id,
                    )
                    continue

                raw_channel_name = str(channel_data.get("displayName") or "").strip()
                channel_display_name = _clean_channel_display_name(
                    device_display_name, raw_channel_name
                )
                base_name = (
                    channel_display_name or device_display_name or f"{serialnumber}/{channel_id}"
                )

                room_name = floorplan.get(floor_id, {}).get(room_id) if room_id else None

                name_id = parse_hex_id(channel_data.get("nameId"))
                position_suffix = (
                    NAME_IDS_TO_BINARY_SENSOR_SUFFIX.get(name_id, "") if name_id is not None else ""
                )
                full_name = f"{self.name_prefix}{base_name}{position_suffix}"

                channel_devices = self._create_channel_devices(
                    sysap_uuid=sysap_uuid,
                    serialnumber=serialnumber,
                    channel_id=channel_id,
                    channel_data=channel_data,
                    function_id=function_id,
                    display_name=full_name,
                    device_info=device_info,
                    is_virtual=is_virtual,
                    initializing=initializing,
                )
                for channel_device in channel_devices:
                    channel_device.room_name = room_name or None
                    channel_device.available = device_data.get("unresponsive") is not True
                created.extend(channel_devices)

        return created

    def _create_channel_devices(
        self,
        *,
        sysap_uuid: str,
        serialnumber: str,
        channel_id: str,
        channel_data: dict[str, Any],
        function_id: int,
        display_name: str,
        device_info: dict[str, Any],
        is_virtual: bool,
        initializing: bool,
    ) -> list[FahBaseDevice]:
        """Match a channel's functionID against device classes and register them."""
        created: list[FahBaseDevice] = []

        for device_cls in DEVICE_CLASSES:
            if device_cls in (FahLight, FahSwitch):
                wanted_pids = device_cls.pairing_ids(function_id, switch_as_x=self.switch_as_x)
            else:
                wanted_pids = device_cls.pairing_ids(function_id)  # type: ignore[attr-defined]

            if wanted_pids is None:
                continue

            matched_dps, dp_values = _match_datapoints(channel_data, wanted_pids)
            if not matched_dps:
                continue

            param_spec = (
                device_cls.parameter_ids(function_id)
                if hasattr(device_cls, "parameter_ids")
                else None
            )
            matched_params, param_values = _match_parameters(channel_data, param_spec)

            split_per_datapoint = device_cls is FahSensor and function_id in (
                FUNCTION_IDS_AIR_QUALITY_SENSOR + FUNCTION_IDS_WEATHER_STATION + FUNCTION_IDS_ENERGY
            )

            dp_groups: list[dict[int, str]]
            if split_per_datapoint:
                dp_groups = [{pid: dp} for pid, dp in matched_dps.items()]
            else:
                dp_groups = [matched_dps]

            for dp_group in dp_groups:
                device = device_cls(
                    self,
                    device_info,
                    serialnumber,
                    channel_id,
                    function_id,
                    display_name,
                    datapoints=dp_group,
                    parameters=matched_params,
                    sysap_uuid=sysap_uuid,
                    is_virtual=is_virtual,
                )
                key = (sysap_uuid, device.lookup_key)
                if key in self._device_keys:
                    continue

                self._device_keys.add(key)
                self.devices.append(device)
                created.append(device)

                for dp_id in dp_group.values():
                    if dp_id.startswith("i"):
                        continue
                    self.monitored_datapoints[
                        (sysap_uuid, f"{serialnumber}/{channel_id}/{dp_id}")
                    ] = device
                    if dp_id in dp_values:
                        device.update_datapoint(dp_id, dp_values[dp_id], initializing=initializing)

                for param_id in matched_params.values():
                    self.monitored_parameters[
                        (sysap_uuid, f"{serialnumber}/{channel_id}/{param_id}")
                    ] = device
                    if param_id in param_values:
                        device.update_parameter(param_id, param_values[param_id])

        return created

    def get_devices(self, platform_type: str) -> list[FahBaseDevice]:
        """Return device models belonging to a Home Assistant platform."""
        mapping: dict[str, tuple[type[FahBaseDevice], ...]] = {
            "light": (FahLight, FahLightGroup),
            "switch": (FahSwitch,),
            "button": (FahTrigger,),
            "scene": (FahScene,),
            "cover": (FahCover,),
            "binary_sensor": (FahBinarySensor,),
            "event": (FahBinarySensor,),
            "thermostat": (FahThermostat,),
            "climate": (FahThermostat,),
            "fan": (FahFan,),
            "sensor": (FahSensor,),
            "lock": (FahLock,),
        }
        classes = mapping.get(platform_type, ())
        return [dev for dev in self.devices if isinstance(dev, classes)]

    async def set_datapoint(
        self,
        serialnumber: str,
        channel_id: str,
        datapoint: str,
        value: str,
        sysap_uuid: str | None = None,
    ) -> Any:
        """Write a datapoint to the SysAP REST API."""
        target_sysap = sysap_uuid or self.primary_sysap_uuid
        return await self.client.set_datapoint(
            target_sysap, serialnumber, channel_id, datapoint, value
        )

    async def set_parameter(
        self,
        serialnumber: str,
        channel_id: str,
        parameter: str,
        value: str,
        sysap_uuid: str | None = None,
    ) -> Any:
        """Write a parameter to the SysAP REST API."""
        target_sysap = sysap_uuid or self.primary_sysap_uuid
        return await self.client.set_parameter(
            target_sysap, serialnumber, channel_id, parameter, value
        )

    async def resync_configuration(self) -> None:
        """Refresh all device datapoint and parameter states after a WebSocket reconnect."""
        config = await self.client.get_configuration()
        self.raw_configuration = config
        updated_devices: set[FahBaseDevice] = set()

        for sysap_uuid, sysap_data in config.items():
            if not isinstance(sysap_data, dict):
                continue
            for serial, dev_data in (sysap_data.get("devices") or {}).items():
                if not isinstance(dev_data, dict):
                    continue
                updated_devices.update(
                    self._update_reachability(
                        sysap_uuid, serial, dev_data.get("unresponsive") is True
                    )
                )
                for channel_id, ch_data in (dev_data.get("channels") or {}).items():
                    if not isinstance(ch_data, dict):
                        continue
                    for section in ("outputs", "inputs"):
                        for dp_id, dp_info in (ch_data.get(section) or {}).items():
                            if (
                                not isinstance(dp_info, dict)
                                or dp_info.get("value") is None
                                or str(dp_info["value"]) == ""
                            ):
                                continue
                            dp_path = f"{serial}/{channel_id}/{dp_id}"
                            device = self.monitored_datapoints.get((sysap_uuid, dp_path))
                            if device is not None:
                                device.update_datapoint(
                                    dp_id, str(dp_info["value"]), initializing=True
                                )
                                updated_devices.add(device)
                    for param_id, param_info in (ch_data.get("parameters") or {}).items():
                        val = (
                            param_info.get("value") if isinstance(param_info, dict) else param_info
                        )
                        if val is None or str(val) == "":
                            continue
                        param_path = f"{serial}/{channel_id}/{param_id}"
                        device = self.monitored_parameters.get((sysap_uuid, param_path))
                        if device is not None:
                            device.update_parameter(param_id, str(val))
                            updated_devices.add(device)

        for device in updated_devices:
            await device.after_update()

    async def _notify_availability(self) -> None:
        """Notify all devices after WebSocket connectivity state changes."""
        for device in list(self.devices):
            await device.after_update()

    def _on_connection_state(self, connected: bool) -> None:
        """Track WebSocket connectivity and notify devices on every change."""
        if connected == self.ws_connected:
            return
        self.ws_connected = connected
        try:
            task = asyncio.get_running_loop().create_task(self._notify_availability())
        except RuntimeError:
            return
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)

    def start_listening(self) -> asyncio.Task[None]:
        """Start the background WebSocket stream as a task owned by the client."""
        return self.client.start_websocket_listener(
            self.handle_ws_message,
            auth_failed_callback=self._auth_failed_cb,
            on_connection_state=self._on_connection_state,
            on_reconnect=self.resync_configuration,
        )

    async def listen(self) -> None:
        """Run the WebSocket stream until closed; for hosts that own the task."""
        await self.client.run_websocket_listener(
            self.handle_ws_message,
            auth_failed_callback=self._auth_failed_cb,
            on_connection_state=self._on_connection_state,
            on_reconnect=self.resync_configuration,
        )

    async def _mirror_virtual_device_feedback(
        self,
        sysap_uuid: str,
        serial: str,
        channel_id: str,
        dp_id: str,
        value: str,
        updated_devices: set[FahBaseDevice],
    ) -> None:
        """Mirror virtual device input commands to output feedback datapoints."""
        for dev in self.devices:
            if (
                dev.sysap_uuid != sysap_uuid
                or dev.serialnumber != serial
                or dev.channel_id != channel_id
            ):
                continue
            matched_in_pid = next(
                (pid for pid, dp in dev._datapoints.items() if dp == dp_id),
                None,
            )
            if matched_in_pid is None:
                continue
            out_pid = VIRTUAL_INPUT_TO_OUTPUT_PID.get(matched_in_pid)
            if out_pid is None or out_pid not in dev._datapoints:
                continue
            odp_id = dev._datapoints[out_pid]
            dev.update_datapoint(odp_id, value, initializing=False)
            updated_devices.add(dev)
            try:
                await self.client.set_datapoint(sysap_uuid, serial, channel_id, odp_id, value)
            except Exception as err:
                _LOGGER.debug(
                    "Virtual device feedback write failed for %s/%s/%s: %s",
                    serial,
                    channel_id,
                    odp_id,
                    err,
                )

    async def handle_ws_message(self, payload: dict[str, Any]) -> None:
        """Process an incoming WebSocket JSON frame from `/fhapi/v1/api/ws`."""
        for listener in list(self._ws_frame_listeners):
            try:
                listener(payload)
            except Exception:
                _LOGGER.exception("WebSocket frame listener failed")

        updated_devices: set[FahBaseDevice] = set()

        for sysap_uuid, frame in payload.items():
            if not isinstance(frame, dict):
                continue

            # 1. Datapoints
            for dp_path, raw_value in (frame.get("datapoints") or {}).items():
                if raw_value is None:
                    continue
                value = str(raw_value)
                parts = dp_path.split("/")
                if len(parts) != 3:
                    continue
                serial, channel_id, dp_id = parts

                device = self.monitored_datapoints.get((sysap_uuid, dp_path))
                if device is not None:
                    device.update_datapoint(dp_id, value, initializing=False)
                    updated_devices.add(device)

                if dp_id.startswith("i") and (
                    (sysap_uuid, serial) in self.virtual_serials
                    or serial.startswith(PROXY_VIRTUAL_SERIAL_PREFIX)
                ):
                    await self._mirror_virtual_device_feedback(
                        sysap_uuid,
                        serial,
                        channel_id,
                        dp_id,
                        value,
                        updated_devices,
                    )
                    for cb in list(self._virtual_cmd_cbs):
                        await cb(sysap_uuid, serial, channel_id, dp_id, value)

            # 2. Parameters
            for param_path, raw_value in (frame.get("parameters") or {}).items():
                extracted = raw_value.get("value") if isinstance(raw_value, dict) else raw_value
                if extracted is None:
                    continue
                value = str(extracted)
                parts = param_path.split("/")
                if len(parts) != 3:
                    continue
                _, _, param_id = parts
                device = self.monitored_parameters.get((sysap_uuid, param_path))
                if device is not None:
                    device.update_parameter(param_id, value)
                    updated_devices.add(device)

            # 3. Scenes Triggered
            scenes_triggered = frame.get("scenesTriggered") or {}
            if scenes_triggered:
                for scene_cb in list(self._scene_triggered_cbs):
                    await scene_cb(sysap_uuid, scenes_triggered)

            # 4. Reachability of known devices (`unresponsive` flag)
            for serial, device_update in (frame.get("devices") or {}).items():
                if isinstance(device_update, dict) and isinstance(
                    device_update.get("unresponsive"), bool
                ):
                    updated_devices.update(
                        self._update_reachability(sysap_uuid, serial, device_update["unresponsive"])
                    )

            # 5. Runtime device additions
            added_devices_payload = dict(frame.get("devices") or {})
            for added_serial in frame.get("devicesAdded") or []:
                if added_serial not in added_devices_payload:
                    try:
                        fetched = await self.client.get_device(sysap_uuid, added_serial)
                        sysap_entry = fetched.get(sysap_uuid, {})
                        devices_block = (
                            sysap_entry.get("devices") if isinstance(sysap_entry, dict) else None
                        )
                        if isinstance(devices_block, dict) and added_serial in devices_block:
                            added_devices_payload[added_serial] = devices_block[added_serial]
                        elif isinstance(fetched.get(added_serial), dict):
                            added_devices_payload[added_serial] = fetched[added_serial]
                    except Exception as err:
                        _LOGGER.debug("Could not fetch added device %s: %s", added_serial, err)

            if added_devices_payload:
                newly_created = self._register_devices_from_dict(
                    sysap_uuid,
                    added_devices_payload,
                    initializing=False,
                )
                if newly_created:
                    for added_cb in list(self._devices_added_cbs):
                        await added_cb(newly_created)

            # 6. Runtime device removals
            for removed_serial in frame.get("devicesRemoved") or []:
                removed = self._forget_device(sysap_uuid, removed_serial)
                for dev in removed:
                    dev.available = False
                    await dev.after_update()
                    updated_devices.discard(dev)
                if removed:
                    for removed_cb in list(self._devices_removed_cbs):
                        await removed_cb(sysap_uuid, removed_serial)

        for device in updated_devices:
            await device.after_update()

    async def validate_connection(self) -> str:
        """Verify credentials and reachability; return primary SysAP title/serial."""
        config = await self._fetch_configuration_with_auth_fallback()
        if not config:
            raise FreeAtHomeAuthError("Empty configuration returned by SysAP")
        first_uuid = next(iter(config))
        sysap_name = (
            config[first_uuid].get("sysapName") if isinstance(config[first_uuid], dict) else None
        )
        return str(sysap_name or self.sysap_serial or self.client.host)

    async def close(self) -> None:
        """Close the underlying client and stop background tasks."""
        self.ws_connected = False
        await self.client.close()
        for task in list(self._pending_tasks):
            task.cancel()
        await asyncio.gather(*self._pending_tasks, return_exceptions=True)
        self._pending_tasks.clear()
