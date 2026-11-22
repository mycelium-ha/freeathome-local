"""Binary sensor device model (wall switches, dimmers, motion, safety, windows)."""

from __future__ import annotations

import logging
import time
from typing import Any

from ..const import (
    FUNCTION_IDS_BINARY_SENSOR,
    FUNCTION_IDS_CONTROL_ELEMENT,
    FUNCTION_IDS_DIMMING_STATUS,
    FUNCTION_IDS_DOOR_CALL_SENSOR,
    FUNCTION_IDS_WEATHER_STATION,
    PID_ADJUST_UP_DOWN,
    PID_BRIGHTNESS_ALARM,
    PID_CO_ALARM_ACTIVE,
    PID_FIRE_ALARM_ACTIVE,
    PID_FORCE_POSITION,
    PID_FORCE_POSITION_BLIND,
    PID_FROST_ALARM,
    PID_MOVE_UP_DOWN,
    PID_MOVEMENT_UNDER_CONSIDERATION_OF_BRIGHTNESS,
    PID_PRESENCE,
    PID_RAIN_ALARM,
    PID_RELATIVE_SET_VALUE,
    PID_SWITCH_ON_OFF,
    PID_SWITCHOVER_HEATING_COOLING,
    PID_TIMED_START_STOP,
    PID_WIND_ALARM,
    PID_WINDOW_DOOR,
    PID_WINDOW_DOOR_POSITION,
)
from .base import FahBaseDevice

_LOGGER = logging.getLogger(__name__)

# free@home cyclically re-sends output datapoints roughly every 840 s as a bus
# keep-alive. Repeating the same value 840 s later is not a new trigger event.
CYCLIC_PERIOD = 840.0
CYCLIC_TOLERANCE = 2.0

WINDOW_POSITION_STATES = {"0": "closed", "33": "tilted", "100": "open"}


class FahBinarySensor(FahBaseDevice):
    """free@home binary sensor & rocker/button event model."""

    def __init__(
        self,
        controller: Any,
        device_info: dict[str, Any],
        serialnumber: str,
        channel_id: str,
        function_id: int | None,
        name: str,
        datapoints: dict[int, str] | None = None,
        parameters: dict[int, str] | None = None,
        sysap_uuid: str = "",
        is_virtual: bool = False,
    ) -> None:
        """Initialize the binary sensor device."""
        super().__init__(
            controller,
            device_info,
            serialnumber,
            channel_id,
            function_id,
            name,
            datapoints=datapoints,
            parameters=parameters,
            sysap_uuid=sysap_uuid,
            is_virtual=is_virtual,
        )
        self.state: str | None = "0" if self.is_door_call_sensor() else None
        self.window_position: str | None = None
        self._cyclic_last: dict[str, tuple[float, str]] = {}
        self._datapoint_updated_cbs: list[Any] = []
        self._pending_datapoint_events: list[dict[str, Any]] = []

    @staticmethod
    def pairing_ids(function_id: int | None = None) -> dict[str, list[int]] | None:
        """Return matching pairing IDs for binary sensors."""
        if function_id in FUNCTION_IDS_BINARY_SENSOR:
            return {
                "inputs": [],
                "outputs": [
                    PID_SWITCH_ON_OFF,
                    PID_TIMED_START_STOP,
                    PID_FORCE_POSITION,
                    PID_RELATIVE_SET_VALUE,
                    PID_MOVE_UP_DOWN,
                    PID_ADJUST_UP_DOWN,
                    PID_WIND_ALARM,
                    PID_FROST_ALARM,
                    PID_RAIN_ALARM,
                    PID_BRIGHTNESS_ALARM,
                    PID_FORCE_POSITION_BLIND,
                    PID_WINDOW_DOOR,
                    PID_WINDOW_DOOR_POSITION,
                    PID_SWITCHOVER_HEATING_COOLING,
                    PID_MOVEMENT_UNDER_CONSIDERATION_OF_BRIGHTNESS,
                    PID_PRESENCE,
                    PID_FIRE_ALARM_ACTIVE,
                    PID_CO_ALARM_ACTIVE,
                ],
            }
        if function_id in FUNCTION_IDS_WEATHER_STATION:
            return {
                "inputs": [],
                "outputs": [
                    PID_WIND_ALARM,
                    PID_FROST_ALARM,
                    PID_BRIGHTNESS_ALARM,
                ],
            }
        return None

    def register_datapoint_updated_cb(self, cb: Any) -> None:
        """Register callback receiving decoded button/dimming events."""
        if cb not in self._datapoint_updated_cbs:
            self._datapoint_updated_cbs.append(cb)

    def unregister_datapoint_updated_cb(self, cb: Any) -> None:
        """Unregister a decoded datapoint callback."""
        if cb in self._datapoint_updated_cbs:
            self._datapoint_updated_cbs.remove(cb)

    async def after_update(self) -> None:
        """Update entity state and emit pending decoded datapoint events."""
        pending = self._pending_datapoint_events
        self._pending_datapoint_events = []

        await super().after_update()

        for event in pending:
            for cb in list(self._datapoint_updated_cbs):
                await cb(self, event)

    def _is_cyclic_repeat(self, dp: str, value: str) -> bool:
        """Return True if `dp` repeated the same value ~840 s after last update."""
        for safety_pid in (PID_FIRE_ALARM_ACTIVE, PID_CO_ALARM_ACTIVE):
            if self._datapoints.get(safety_pid) == dp:
                return False

        now = time.monotonic()
        previous = self._cyclic_last.get(dp)
        self._cyclic_last[dp] = (now, value)

        if previous is None:
            return False
        last_time, last_value = previous
        if value != last_value:
            return False
        return abs((now - last_time) - CYCLIC_PERIOD) <= CYCLIC_TOLERANCE

    @staticmethod
    def _relative_dimming_event(value: str) -> dict[str, Any] | None:
        """Decode KNX DPT 3.007 relative dimming values."""
        try:
            raw_value = int(value)
        except TypeError, ValueError:
            return None
        if not 0 <= raw_value <= 0x0F:
            return None

        direction = "up" if raw_value & 0x08 else "down"
        step_code = raw_value & 0x07
        command = "dim_stop" if step_code == 0 else "dim_start"

        return {
            "pid": PID_RELATIVE_SET_VALUE,
            "raw_value": value,
            "command": command,
            "direction": direction,
        }

    def update_datapoint(self, dp: str, value: str, *, initializing: bool = False) -> None:
        """Handle binary sensor datapoint updates."""
        if value is None or value == "":
            return

        if initializing and self.is_door_call_sensor():
            self.state = "0"
            return

        if self._datapoints.get(PID_WINDOW_DOOR_POSITION) == dp:
            self.window_position = value
            return

        if not initializing and self._is_cyclic_repeat(dp, value):
            _LOGGER.debug(
                "Binary sensor %s (%s) dp %s cyclic repeat %s ignored",
                self.name,
                self.lookup_key,
                dp,
                value,
            )
            return

        if self._datapoints.get(PID_RELATIVE_SET_VALUE) == dp:
            event = self._relative_dimming_event(value)
            if event is None:
                return
            self.state = "0" if event["command"] == "dim_stop" else "1"
            if not initializing:
                self._pending_datapoint_events.append(event)
            return

        self.state = "0" if value == "0" else "1"
        if not initializing:
            pid = next(
                (p for p, datapoint in self._datapoints.items() if datapoint == dp),
                None,
            )
            self._pending_datapoint_events.append(
                {
                    "pid": pid,
                    "raw_value": value,
                    "command": "pressed",
                    "state": self.state == "1",
                }
            )

    def is_fire_sensor(self) -> bool:
        """Return True for smoke/fire detectors."""
        return PID_FIRE_ALARM_ACTIVE in self._datapoints

    def is_co_sensor(self) -> bool:
        """Return True for CO detectors."""
        return PID_CO_ALARM_ACTIVE in self._datapoints

    def is_door_call_sensor(self) -> bool:
        """Return True for door entry ringing sensors."""
        return self._function_id in FUNCTION_IDS_DOOR_CALL_SENSOR

    def is_window_door_sensor(self) -> bool:
        """Return True for window/door contact sensors."""
        return (
            self._function_id in (0x000F, 0x0064, 0x0114)
            or PID_WINDOW_DOOR in self._datapoints
            or PID_WINDOW_DOOR_POSITION in self._datapoints
        )

    def supports_window_position(self) -> bool:
        """Return True if the sensor reports the window position (closed/tilted/open)."""
        return PID_WINDOW_DOOR_POSITION in self._datapoints

    @property
    def window_position_state(self) -> str | None:
        """Return the window position as `closed`, `tilted` or `open`, if known."""
        return WINDOW_POSITION_STATES.get(self.window_position or "")

    def is_motion_sensor(self) -> bool:
        """Return True for motion and presence detectors."""
        return (
            self._function_id
            in (0x0011, 0x0115, 0x1090, 0x1091, 0x1092, 0x1093, 0x1094, 0x1095, 0x1096)
            or PID_MOVEMENT_UNDER_CONSIDERATION_OF_BRIGHTNESS in self._datapoints
            or PID_PRESENCE in self._datapoints
        )

    def is_rain_sensor(self) -> bool:
        """Return True for rain alarm sensors."""
        return self._function_id == 0x000E or PID_RAIN_ALARM in self._datapoints

    def is_frost_sensor(self) -> bool:
        """Return True for frost alarm sensors."""
        return self._function_id == 0x000D or PID_FROST_ALARM in self._datapoints

    def is_wind_sensor(self) -> bool:
        """Return True for wind alarm sensors."""
        return self._function_id == 0x000C or PID_WIND_ALARM in self._datapoints

    def is_control_element(self) -> bool:
        """Return True for wall rockers, push buttons and panel buttons."""
        return self._function_id in FUNCTION_IDS_CONTROL_ELEMENT

    def supports_hold_events(self) -> bool:
        """Return True if the control reports long presses (relative dimming)."""
        return PID_RELATIVE_SET_VALUE in self._datapoints

    def supports_dimming_status(self) -> bool:
        """Return True if this channel exposes two-sided dimming rocker events."""
        return (
            self._function_id in FUNCTION_IDS_DIMMING_STATUS
            and PID_RELATIVE_SET_VALUE in self._datapoints
        )
