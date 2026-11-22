"""Ceiling fan actuator device model."""

from __future__ import annotations

import contextlib
from typing import Any

from ..const import (
    FUNCTION_IDS_CEILING_FAN,
    PID_ABSOLUTE_SET_VALUE,
    PID_FAN_SPEED,
    PID_INFO_ACTUAL_DIMMING_VALUE,
    PID_INFO_FAN_SPEED,
    PID_INFO_ON_OFF,
    PID_SWITCH_ON_OFF,
)
from .base import FahBaseDevice


class FahFan(FahBaseDevice):
    """free@home ceiling fan actuator (`0x00A8`)."""

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
        """Initialize the ceiling fan device."""
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
        self.state: bool | None = None
        self.percentage: int | None = None

    @staticmethod
    def pairing_ids(function_id: int | None = None) -> dict[str, list[int]] | None:
        """Return matching pairing IDs for ceiling fans."""
        if function_id in FUNCTION_IDS_CEILING_FAN:
            return {
                "inputs": [PID_SWITCH_ON_OFF, PID_ABSOLUTE_SET_VALUE, PID_FAN_SPEED],
                "outputs": [
                    PID_INFO_ON_OFF,
                    PID_INFO_ACTUAL_DIMMING_VALUE,
                    PID_INFO_FAN_SPEED,
                ],
            }
        return None

    def supports_percentage(self) -> bool:
        """Return True if variable speed percentage is available."""
        return PID_ABSOLUTE_SET_VALUE in self._datapoints or PID_FAN_SPEED in self._datapoints

    async def turn_on(self, percentage: int | None = None) -> None:
        """Turn the fan on and optionally set speed percentage."""
        await self.set_datapoint(PID_SWITCH_ON_OFF, "1")
        self.state = True
        if percentage is not None:
            await self.set_percentage(percentage)

    async def turn_off(self) -> None:
        """Turn the fan off."""
        await self.set_datapoint(PID_SWITCH_ON_OFF, "0")
        self.state = False

    async def set_percentage(self, percentage: int) -> None:
        """Set fan speed percentage (0..100)."""
        clamped = max(0, min(100, int(percentage)))
        if clamped == 0:
            await self.turn_off()
            self.percentage = 0
            return
        if PID_FAN_SPEED in self._datapoints:
            await self.set_datapoint(PID_FAN_SPEED, str(clamped))
        elif PID_ABSOLUTE_SET_VALUE in self._datapoints:
            await self.set_datapoint(PID_ABSOLUTE_SET_VALUE, str(clamped))
        self.percentage = clamped
        self.state = True

    def update_datapoint(self, dp: str, value: str, *, initializing: bool = False) -> None:
        """Update fan state and speed percentage."""
        if self._datapoints.get(PID_INFO_ON_OFF) == dp:
            self.state = value == "1"
        elif self._datapoints.get(PID_INFO_FAN_SPEED) == dp or (
            self._datapoints.get(PID_INFO_ACTUAL_DIMMING_VALUE) == dp
        ):
            with contextlib.suppress(TypeError, ValueError):
                self.percentage = max(0, min(100, int(float(value))))
