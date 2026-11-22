"""Cover (blind, shutter, attic window, awning, shutter group) device model."""

from __future__ import annotations

import contextlib
from typing import Any

from ..const import (
    FUNCTION_IDS_ATTIC_WINDOW_ACTUATOR,
    FUNCTION_IDS_AWNING_ACTUATOR,
    FUNCTION_IDS_BLIND_ACTUATOR,
    FUNCTION_IDS_SHUTTER_ACTUATOR,
    FUNCTION_IDS_SHUTTER_GROUP,
    PID_ADJUST_UP_DOWN,
    PID_CURRENT_ABSOLUTE_POSITION_BLINDS_PERCENTAGE,
    PID_CURRENT_ABSOLUTE_POSITION_SLATS_PERCENTAGE,
    PID_FORCE_POSITION_BLIND,
    PID_FORCE_POSITION_INFO,
    PID_INFO_MOVE_UP_DOWN,
    PID_MOVE_UP_DOWN,
    PID_SET_ABSOLUTE_POSITION_BLINDS,
    PID_SET_ABSOLUTE_POSITION_SLATS,
    PID_SYSAP_CURRENT_ABSOLUTE_POSITION_BLINDS_PERCENTAGE,
    PID_SYSAP_CURRENT_ABSOLUTE_POSITION_SLATS_PERCENTAGE,
    PID_SYSAP_FORCE_POSITION_INFO,
    PID_SYSAP_INFO_MOVE_UP_DOWN,
)
from .base import FahBaseDevice

FORCE_POSITION_COMMANDS = {
    "none": "1",
    "open": "2",
    "closed": "3",
}

FORCE_POSITION_STATES = {
    "0": "none",
    "1": "none",
    "2": "open",
    "3": "closed",
}


class FahCover(FahBaseDevice):
    """free@home cover device.

    In free@home, position 100 means fully closed, while in Home Assistant 100
    means fully open. Conversions between the two happen cleanly at the boundary.
    """

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
        """Initialize cover device."""
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
        self.state: str | None = None
        self.position: int | None = None
        self.tilt_position: int | None = None
        self.forced_position: str | None = None

    @staticmethod
    def pairing_ids(function_id: int | None = None) -> dict[str, list[int]] | None:
        """Return matching pairing IDs for cover functions."""
        if (
            function_id in FUNCTION_IDS_BLIND_ACTUATOR
            or function_id in FUNCTION_IDS_ATTIC_WINDOW_ACTUATOR
            or function_id in FUNCTION_IDS_AWNING_ACTUATOR
        ):
            return {
                "inputs": [
                    PID_MOVE_UP_DOWN,
                    PID_ADJUST_UP_DOWN,
                    PID_SET_ABSOLUTE_POSITION_BLINDS,
                    PID_FORCE_POSITION_BLIND,
                ],
                "outputs": [
                    PID_INFO_MOVE_UP_DOWN,
                    PID_CURRENT_ABSOLUTE_POSITION_BLINDS_PERCENTAGE,
                    PID_FORCE_POSITION_INFO,
                ],
            }
        if function_id in FUNCTION_IDS_SHUTTER_GROUP:
            group_pids = [
                PID_MOVE_UP_DOWN,
                PID_ADJUST_UP_DOWN,
                PID_SET_ABSOLUTE_POSITION_BLINDS,
                PID_FORCE_POSITION_BLIND,
                PID_INFO_MOVE_UP_DOWN,
                PID_CURRENT_ABSOLUTE_POSITION_BLINDS_PERCENTAGE,
                PID_FORCE_POSITION_INFO,
                PID_SYSAP_INFO_MOVE_UP_DOWN,
                PID_SYSAP_CURRENT_ABSOLUTE_POSITION_BLINDS_PERCENTAGE,
                PID_SYSAP_FORCE_POSITION_INFO,
            ]
            return {"inputs": list(group_pids), "outputs": list(group_pids)}
        if function_id in FUNCTION_IDS_SHUTTER_ACTUATOR:
            return {
                "inputs": [
                    PID_MOVE_UP_DOWN,
                    PID_ADJUST_UP_DOWN,
                    PID_SET_ABSOLUTE_POSITION_BLINDS,
                    PID_SET_ABSOLUTE_POSITION_SLATS,
                    PID_FORCE_POSITION_BLIND,
                ],
                "outputs": [
                    PID_INFO_MOVE_UP_DOWN,
                    PID_CURRENT_ABSOLUTE_POSITION_BLINDS_PERCENTAGE,
                    PID_CURRENT_ABSOLUTE_POSITION_SLATS_PERCENTAGE,
                    PID_FORCE_POSITION_INFO,
                ],
            }
        return None

    def is_cover_closed(self) -> bool | None:
        """Return True if cover is fully closed."""
        if self.supports_position() and self.position is not None:
            return self.position == 0
        return None

    def is_cover_opening(self) -> bool:
        """Return True if cover is currently moving up."""
        return self.state == "2"

    def is_cover_closing(self) -> bool:
        """Return True if cover is currently moving down."""
        return self.state == "3"

    def get_cover_position(self) -> int | None:
        """Return cover position (0 = closed, 100 = open)."""
        if self.supports_position():
            return self.position
        return None

    def get_cover_tilt_position(self) -> int | None:
        """Return slat tilt position (0 = closed, 100 = open)."""
        if self.supports_tilt_position():
            return self.tilt_position
        return None

    def get_forced_cover_position(self) -> str | None:
        """Return current forced position mode."""
        if self.supports_forced_position() and self.forced_position is not None:
            return FORCE_POSITION_STATES.get(self.forced_position)
        return None

    async def set_cover_position(self, position: int) -> None:
        """Move cover to target HA position (0..100)."""
        await self.set_datapoint(PID_SET_ABSOLUTE_POSITION_BLINDS, str(abs(100 - int(position))))

    async def set_cover_tilt_position(self, tilt_position: int) -> None:
        """Adjust slat tilt to target HA position (0..100)."""
        await self.set_datapoint(
            PID_SET_ABSOLUTE_POSITION_SLATS, str(abs(100 - int(tilt_position)))
        )

    async def set_forced_cover_position(self, forced_position: str) -> None:
        """Force cover to remain open, closed, or release forced mode."""
        command = FORCE_POSITION_COMMANDS.get(forced_position.lower())
        if command is not None:
            await self.set_datapoint(PID_FORCE_POSITION_BLIND, command)

    async def open_cover(self) -> None:
        """Open the cover."""
        await self.set_datapoint(PID_MOVE_UP_DOWN, "0")

    async def close_cover(self) -> None:
        """Close the cover."""
        await self.set_datapoint(PID_MOVE_UP_DOWN, "1")

    async def stop_cover(self) -> None:
        """Stop cover movement."""
        if self.supports_stop() and self.state in ("2", "3"):
            await self.set_datapoint(PID_ADJUST_UP_DOWN, "1")

    def supports_position(self) -> bool:
        """Return True if absolute positioning is supported."""
        return PID_SET_ABSOLUTE_POSITION_BLINDS in self._datapoints

    def supports_tilt_position(self) -> bool:
        """Return True if slat tilt positioning is supported."""
        return PID_SET_ABSOLUTE_POSITION_SLATS in self._datapoints

    def supports_stop(self) -> bool:
        """Return True if stop command is supported."""
        return PID_ADJUST_UP_DOWN in self._datapoints

    def supports_forced_position(self) -> bool:
        """Return True if forced position is supported."""
        return PID_FORCE_POSITION_BLIND in self._datapoints

    def device_class(self) -> str | None:
        """Return cover device class string."""
        if self._function_id in FUNCTION_IDS_ATTIC_WINDOW_ACTUATOR:
            return "window"
        if self._function_id in FUNCTION_IDS_AWNING_ACTUATOR:
            return "awning"
        if self._function_id in FUNCTION_IDS_SHUTTER_ACTUATOR:
            return "shutter"
        return "blind"

    def update_datapoint(self, dp: str, value: str, *, initializing: bool = False) -> None:
        """Update cover state from incoming datapoint."""
        if dp in (
            self._datapoints.get(PID_INFO_MOVE_UP_DOWN),
            self._datapoints.get(PID_SYSAP_INFO_MOVE_UP_DOWN),
        ):
            self.state = value
        elif dp in (
            self._datapoints.get(PID_CURRENT_ABSOLUTE_POSITION_BLINDS_PERCENTAGE),
            self._datapoints.get(PID_SYSAP_CURRENT_ABSOLUTE_POSITION_BLINDS_PERCENTAGE),
        ):
            with contextlib.suppress(TypeError, ValueError):
                self.position = abs(100 - int(float(value)))
        elif dp in (
            self._datapoints.get(PID_CURRENT_ABSOLUTE_POSITION_SLATS_PERCENTAGE),
            self._datapoints.get(PID_SYSAP_CURRENT_ABSOLUTE_POSITION_SLATS_PERCENTAGE),
        ):
            with contextlib.suppress(TypeError, ValueError):
                self.tilt_position = abs(100 - int(float(value)))
        elif dp in (
            self._datapoints.get(PID_FORCE_POSITION_INFO),
            self._datapoints.get(PID_SYSAP_FORCE_POSITION_INFO),
        ):
            self.forced_position = value
