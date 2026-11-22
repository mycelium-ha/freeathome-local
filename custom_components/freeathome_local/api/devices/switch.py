"""Switch and timer profile actuator device models."""

from __future__ import annotations

from typing import Any

from ..const import (
    FUNCTION_IDS_SWITCHING_ACTUATOR,
    FUNCTION_IDS_SYSTEM_SWITCH,
    FUNCTION_IDS_TIMER_PROFILE,
    PID_INFO_ON_OFF,
    PID_INFO_TIMER_PROGRAM_SWITCH_ON_OFF,
    PID_NIGHT_ACTUATOR_FOR_SYSAP,
    PID_NIGHT_INFO,
    PID_SWITCH_ON_OFF,
    PID_TIMED_START_STOP,
    PID_TIMER_PROGRAM_SWITCH_ON_OFF,
)
from .base import FahBaseDevice


class FahSwitch(FahBaseDevice):
    """free@home switching actuator, DES system switch, or timer program switch."""

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
        """Initialize the switch device."""
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

    @staticmethod
    def pairing_ids(
        function_id: int | None = None, switch_as_x: bool = True
    ) -> dict[str, list[int]] | None:
        """Return pairing IDs for switch actuators, system switches, and timer switches."""
        if function_id in FUNCTION_IDS_SWITCHING_ACTUATOR and switch_as_x:
            return {
                "inputs": [PID_SWITCH_ON_OFF],
                "outputs": [PID_INFO_ON_OFF],
            }
        if function_id in (FUNCTION_IDS_TIMER_PROFILE + FUNCTION_IDS_SYSTEM_SWITCH):
            return {
                "inputs": [
                    PID_SWITCH_ON_OFF,
                    PID_TIMED_START_STOP,
                    PID_NIGHT_ACTUATOR_FOR_SYSAP,
                    PID_TIMER_PROGRAM_SWITCH_ON_OFF,
                ],
                "outputs": [
                    PID_INFO_ON_OFF,
                    PID_NIGHT_INFO,
                    PID_INFO_TIMER_PROGRAM_SWITCH_ON_OFF,
                ],
            }
        return None

    def _resolve_input_pid(self) -> int:
        """Return the active input pairing ID for this switch channel."""
        for candidate in (
            PID_TIMER_PROGRAM_SWITCH_ON_OFF,
            PID_NIGHT_ACTUATOR_FOR_SYSAP,
            PID_TIMED_START_STOP,
            PID_SWITCH_ON_OFF,
        ):
            if candidate in self._datapoints:
                return candidate
        return PID_SWITCH_ON_OFF

    async def turn_on(self) -> None:
        """Turn the switch on."""
        await self.set_datapoint(self._resolve_input_pid(), "1")
        self.state = True

    async def turn_off(self) -> None:
        """Turn the switch off."""
        await self.set_datapoint(self._resolve_input_pid(), "0")
        self.state = False

    def is_on(self) -> bool | None:
        """Return True when the switch is on."""
        return self.state

    def update_datapoint(self, dp: str, value: str, *, initializing: bool = False) -> None:
        """Update switch state from output datapoint."""
        if dp in (
            self._datapoints.get(PID_INFO_ON_OFF),
            self._datapoints.get(PID_NIGHT_INFO),
            self._datapoints.get(PID_INFO_TIMER_PROGRAM_SWITCH_ON_OFF),
        ):
            self.state = value == "1"
